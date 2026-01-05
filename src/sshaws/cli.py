#!/usr/bin/env python3
"""
sshaws - SSH to AWS EC2 instances via SSM

A drop-in SSH replacement for connecting to private EC2 instances through AWS SSM.
Mimics standard SSH CLI behavior.

Usage:
    sshaws [user@]<instance-id> [options]
    sshaws list [options]
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound


@dataclass
class ForwardingOptions:
    """Port forwarding options."""

    local: List[str] = field(default_factory=list)
    remote: List[str] = field(default_factory=list)
    dynamic: Optional[str] = None


@dataclass
class TerminalOptions:
    """Terminal and execution options."""

    verbose: int = 0
    no_tty: bool = False
    force_tty: bool = False
    no_command: bool = False


@dataclass
class SSHOptions:
    """Options for SSH connection."""

    identity_file: Optional[str] = None
    port: int = 22
    forwarding: ForwardingOptions = field(default_factory=ForwardingOptions)
    terminal: TerminalOptions = field(default_factory=TerminalOptions)
    extra_options: List[str] = field(default_factory=list)
    remote_command: List[str] = field(default_factory=list)


class SSHAWSClient:
    """AWS SSM-based SSH client."""

    def __init__(self, profile: Optional[str] = None, region: Optional[str] = None):
        session_kwargs = {}
        if profile:
            session_kwargs['profile_name'] = profile
        if region:
            session_kwargs['region_name'] = region

        try:
            self.session = boto3.Session(**session_kwargs)
            self.ssm = self.session.client('ssm')
            self.ec2 = self.session.client('ec2')
            self.region = self.session.region_name
        except ProfileNotFound:
            print(f"Error: AWS profile '{profile}' not found", file=sys.stderr)
            sys.exit(1)
        except NoCredentialsError:
            print("Error: AWS credentials not configured", file=sys.stderr)
            print("Run 'aws configure' or set AWS_PROFILE environment variable",
                  file=sys.stderr)
            sys.exit(1)

    def list_instances(self, show_all: bool = False) -> List[Dict]:
        """List EC2 instances with SSM availability."""
        try:
            ssm_response = self.ssm.describe_instance_information()
            ssm_instances = {
                i['InstanceId']: i
                for i in ssm_response.get('InstanceInformationList', [])
            }

            ec2_response = self.ec2.describe_instances()
            instances = []

            for reservation in ec2_response['Reservations']:
                for instance in reservation['Instances']:
                    instance_data = self._process_instance(
                        instance, ssm_instances, show_all
                    )
                    if instance_data:
                        instances.append(instance_data)

            return sorted(instances, key=lambda x: (not x['ssm_available'], x['name']))

        except ClientError as e:
            print(f"Error listing instances: {e}", file=sys.stderr)
            return []

    def _process_instance(
        self, instance: Dict, ssm_instances: Dict, show_all: bool
    ) -> Optional[Dict]:
        """Process a single EC2 instance and return its data."""
        instance_id = instance['InstanceId']
        state = instance['State']['Name']

        if state == 'terminated':
            return None

        ssm_info = ssm_instances.get(instance_id)
        if not ssm_info and not show_all:
            return None

        name = next(
            (t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'),
            '-'
        )

        is_online = ssm_info is not None and ssm_info.get('PingStatus') == 'Online'

        return {
            'instance_id': instance_id,
            'name': name,
            'state': state,
            'private_ip': instance.get('PrivateIpAddress', '-'),
            'public_ip': instance.get('PublicIpAddress', '-'),
            'platform': ssm_info.get('PlatformType', '-') if ssm_info else '-',
            'ssm_status': ssm_info.get('PingStatus', 'Offline') if ssm_info else 'No Agent',
            'ssm_available': is_online
        }

    def get_default_user(self, instance_id: str) -> str:
        """Determine default SSH user based on AMI/platform."""
        try:
            response = self.ssm.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            instances = response.get('InstanceInformationList', [])
            if instances:
                platform = instances[0].get('PlatformName', '').lower()
                if 'ubuntu' in platform:
                    return 'ubuntu'
                if 'debian' in platform:
                    return 'admin'
                if 'centos' in platform:
                    return 'centos'
                if 'rhel' in platform:
                    return 'ec2-user'
        except ClientError:
            pass
        return 'ec2-user'

    def check_ssm_available(self, instance_id: str) -> Tuple[bool, str]:
        """Check if instance is reachable via SSM."""
        try:
            response = self.ssm.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            instances = response.get('InstanceInformationList', [])
            if not instances:
                return False, "Instance not found in SSM. Check SSM agent is running."

            status = instances[0].get('PingStatus', 'Unknown')
            if status == 'Online':
                return True, "Online"
            return False, f"SSM agent status: {status}"
        except ClientError as e:
            return False, str(e)

    def _build_proxy_command(self, instance_id: str, port: int) -> str:
        """Build the SSM proxy command string."""
        proxy_parts = [
            'aws', 'ssm', 'start-session',
            '--target', instance_id,
            '--document-name', 'AWS-StartSSHSession',
            '--parameters', f'portNumber={port}'
        ]

        if self.session.profile_name:
            proxy_parts.extend(['--profile', self.session.profile_name])
        if self.region:
            proxy_parts.extend(['--region', self.region])

        return ' '.join(proxy_parts)

    def _add_ssh_options(self, ssh_cmd: List[str], opts: SSHOptions) -> None:
        """Add SSH options to the command list."""
        if opts.identity_file:
            ssh_cmd.extend(['-i', opts.identity_file])

        if opts.port != 22:
            ssh_cmd.extend(['-p', str(opts.port)])

        for fwd in opts.forwarding.local:
            ssh_cmd.extend(['-L', fwd])

        for fwd in opts.forwarding.remote:
            ssh_cmd.extend(['-R', fwd])

        if opts.forwarding.dynamic:
            ssh_cmd.extend(['-D', opts.forwarding.dynamic])

        if opts.terminal.verbose > 0:
            ssh_cmd.append('-' + 'v' * min(opts.terminal.verbose, 3))

        if opts.terminal.no_tty:
            ssh_cmd.append('-T')

        if opts.terminal.force_tty:
            ssh_cmd.append('-t')

        if opts.terminal.no_command:
            ssh_cmd.append('-N')

        for opt in opts.extra_options:
            ssh_cmd.extend(['-o', opt])

    def build_ssh_command(
        self, instance_id: str, user: str, opts: SSHOptions
    ) -> List[str]:
        """Build the SSH command with SSM ProxyCommand."""
        proxy_cmd = self._build_proxy_command(instance_id, opts.port)

        ssh_cmd = ['ssh']
        ssh_cmd.extend(['-o', f'ProxyCommand={proxy_cmd}'])
        ssh_cmd.extend(['-o', 'StrictHostKeyChecking=accept-new'])
        ssh_cmd.extend(['-o', 'UserKnownHostsFile=/dev/null'])
        ssh_cmd.extend(['-o', 'LogLevel=ERROR'])

        self._add_ssh_options(ssh_cmd, opts)

        ssh_cmd.append(f'{user}@{instance_id}')

        if opts.remote_command:
            ssh_cmd.extend(opts.remote_command)

        return ssh_cmd

    def connect(self, instance_id: str, user: str, opts: SSHOptions) -> int:
        """Execute SSH connection."""
        available, status = self.check_ssm_available(instance_id)
        if not available:
            print(f"Error: Cannot connect to {instance_id}", file=sys.stderr)
            print(f"Reason: {status}", file=sys.stderr)
            return 1

        ssh_cmd = self.build_ssh_command(instance_id, user, opts)

        if opts.terminal.verbose > 0:
            print(f"Executing: {' '.join(ssh_cmd)}", file=sys.stderr)

        return subprocess.call(ssh_cmd)

    def start_ssm_session(self, instance_id: str) -> int:
        """Start direct SSM session (no SSH)."""
        cmd = ['aws', 'ssm', 'start-session', '--target', instance_id]

        if self.session.profile_name:
            cmd.extend(['--profile', self.session.profile_name])
        if self.region:
            cmd.extend(['--region', self.region])

        return subprocess.call(cmd)


def parse_destination(dest: str) -> Tuple[Optional[str], str]:
    """Parse [user@]instance-id format."""
    if '@' in dest:
        user, instance_id = dest.split('@', 1)
        return user, instance_id
    return None, dest


def format_instance_list(instances: List[Dict], output_format: str = 'table') -> str:
    """Format instance list for display."""
    if not instances:
        return "No instances found."

    if output_format == 'json':
        return json.dumps(instances, indent=2)

    if output_format == 'simple':
        lines = []
        for i in instances:
            status = '✓' if i['ssm_available'] else '✗'
            lines.append(
                f"{status} {i['instance_id']}\t{i['name']}\t{i['private_ip']}"
            )
        return '\n'.join(lines)

    return _format_table(instances)


def _format_table(instances: List[Dict]) -> str:
    """Format instances as a table."""
    header = (
        f"{'SSM':<4} {'Instance ID':<20} {'Name':<28} "
        f"{'State':<10} {'Private IP':<15} {'Platform':<10}"
    )
    separator = '-' * len(header)
    lines = [header, separator]

    for i in instances:
        status = '✓' if i['ssm_available'] else '✗'
        name = i['name'][:27] + '…' if len(i['name']) > 28 else i['name']
        lines.append(
            f"{status:<4} {i['instance_id']:<20} {name:<28} {i['state']:<10} "
            f"{i['private_ip']:<15} {i['platform']:<10}"
        )

    return '\n'.join(lines)


def parse_list_command(args: List[str]) -> Tuple[Optional[str], Optional[str], bool, str]:
    """Parse list subcommand arguments.

    Returns:
        Tuple of (profile, region, show_all, output_format)
    """
    profile = None
    region = None
    show_all = False
    output_format = 'table'

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('--profile', '-P') and i + 1 < len(args):
            profile = args[i + 1]
            i += 2
        elif arg == '--region' and i + 1 < len(args):
            region = args[i + 1]
            i += 2
        elif arg in ('-a', '--all'):
            show_all = True
            i += 1
        elif arg in ('-o', '--output') and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        elif arg.startswith('--profile='):
            profile = arg.split('=', 1)[1]
            i += 1
        elif arg.startswith('--region='):
            region = arg.split('=', 1)[1]
            i += 1
        elif arg.startswith('--output='):
            output_format = arg.split('=', 1)[1]
            i += 1
        else:
            i += 1

    return profile, region, show_all, output_format


def _is_list_command() -> bool:
    """Check if the current command is a list command."""
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in ('--profile', '-P', '--region', '-i', '-p', '-l',
                   '-L', '-R', '-D', '-o'):
            skip_next = True
            continue
        if arg.startswith('-'):
            continue
        return arg == 'list'
    return False


def _handle_list_command() -> int:
    """Handle the list subcommand."""
    profile, region, show_all, output_format = parse_list_command(sys.argv[1:])
    client = SSHAWSClient(profile=profile, region=region)
    instances = client.list_instances(show_all=show_all)
    print(format_instance_list(instances, output_format))
    return 0


def _create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog='sshaws',
        description='SSH to AWS EC2 instances via SSM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sshaws i-0123456789abcdef0              # Connect as ec2-user
  sshaws ubuntu@i-0123456789abcdef0       # Connect as ubuntu
  sshaws -i ~/.ssh/key.pem i-xxx          # With identity file
  sshaws -L 8080:localhost:80 i-xxx       # Local port forward
  sshaws -D 1080 i-xxx                    # SOCKS proxy
  sshaws list                             # List SSM-enabled instances
  sshaws list --all                       # List all instances
  sshaws list -o json                     # JSON output

Prerequisites:
  - AWS CLI v2
  - Session Manager Plugin
        """
    )

    parser.add_argument('--profile', '-P', metavar='NAME',
                        help='AWS profile name')
    parser.add_argument('--region', metavar='REGION',
                        help='AWS region')
    parser.add_argument('destination', nargs='?', metavar='[user@]instance-id',
                        help='Target instance (e.g., i-xxx or ec2-user@i-xxx)')
    parser.add_argument('-i', dest='identity_file', metavar='FILE',
                        help='Identity file (private key)')
    parser.add_argument('-p', dest='port', type=int, default=22,
                        help='Port to connect to (default: 22)')
    parser.add_argument('-l', dest='login_name', metavar='USER',
                        help='Login name')
    parser.add_argument('-L', dest='local_forward', action='append',
                        metavar='FORWARD', help='Local port forward')
    parser.add_argument('-R', dest='remote_forward', action='append',
                        metavar='FORWARD', help='Remote port forward')
    parser.add_argument('-D', dest='dynamic_forward', metavar='PORT',
                        help='Dynamic SOCKS proxy')
    parser.add_argument('-N', dest='no_command', action='store_true',
                        help='Do not execute remote command')
    parser.add_argument('-T', dest='no_tty', action='store_true',
                        help='Disable pseudo-terminal allocation')
    parser.add_argument('-t', dest='force_tty', action='store_true',
                        help='Force pseudo-terminal allocation')
    parser.add_argument('-v', dest='verbose', action='count', default=0,
                        help='Verbose mode (can be repeated)')
    parser.add_argument('-o', dest='options', action='append', metavar='option',
                        help='SSH option (can be repeated)')
    parser.add_argument('--ssm', action='store_true',
                        help='Use direct SSM session instead of SSH')
    parser.add_argument('remote_command', nargs='*', metavar='command',
                        help='Command to execute on remote host')

    return parser


def _handle_ssh_command(args: argparse.Namespace) -> int:
    """Handle SSH connection command."""
    if not args.destination:
        return 1

    user, instance_id = parse_destination(args.destination)

    if not re.match(r'^i-[a-f0-9]{8,17}$', instance_id):
        print(f"Error: Invalid instance ID format: {instance_id}", file=sys.stderr)
        print("Instance ID should match pattern: i-xxxxxxxxxxxxxxxxx",
              file=sys.stderr)
        return 1

    client = SSHAWSClient(profile=args.profile, region=args.region)

    if args.login_name:
        user = args.login_name
    elif not user:
        user = client.get_default_user(instance_id)

    if args.ssm:
        return client.start_ssm_session(instance_id)

    forwarding = ForwardingOptions(
        local=args.local_forward or [],
        remote=args.remote_forward or [],
        dynamic=args.dynamic_forward
    )

    terminal = TerminalOptions(
        verbose=args.verbose,
        no_tty=args.no_tty,
        force_tty=args.force_tty,
        no_command=args.no_command
    )

    opts = SSHOptions(
        identity_file=args.identity_file,
        port=args.port,
        forwarding=forwarding,
        terminal=terminal,
        extra_options=args.options or [],
        remote_command=args.remote_command or []
    )

    return client.connect(instance_id=instance_id, user=user, opts=opts)


def main() -> int:
    """Main entry point for sshaws CLI."""
    if _is_list_command():
        return _handle_list_command()

    parser = _create_parser()
    args = parser.parse_args()

    if not args.destination:
        parser.print_help()
        return 1

    return _handle_ssh_command(args)


if __name__ == '__main__':
    sys.exit(main())
