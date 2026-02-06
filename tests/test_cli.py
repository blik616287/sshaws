"""Tests for sshaws CLI module."""

import json
import sys
import pytest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from sshaws.cli import (
    SSHAWSClient,
    SSHOptions,
    ForwardingOptions,
    TerminalOptions,
    parse_destination,
    format_instance_list,
    parse_list_command,
    main,
)


class TestSSHAWSClientInit:
    """Tests for SSHAWSClient initialization."""

    def test_init_default(self, mock_boto3_session):
        """Test default initialization."""
        client = SSHAWSClient()
        mock_boto3_session['session_class'].assert_called_once_with()
        assert client.region == 'us-east-1'

    def test_init_with_profile(self, mock_boto3_session):
        """Test initialization with profile."""
        client = SSHAWSClient(profile='myprofile')
        mock_boto3_session['session_class'].assert_called_once_with(
            profile_name='myprofile'
        )

    def test_init_with_region(self, mock_boto3_session):
        """Test initialization with region."""
        client = SSHAWSClient(region='us-west-2')
        mock_boto3_session['session_class'].assert_called_once_with(
            region_name='us-west-2'
        )

    def test_init_with_profile_and_region(self, mock_boto3_session):
        """Test initialization with both profile and region."""
        client = SSHAWSClient(profile='myprofile', region='eu-west-1')
        mock_boto3_session['session_class'].assert_called_once_with(
            profile_name='myprofile',
            region_name='eu-west-1'
        )

    def test_init_profile_not_found(self):
        """Test initialization with non-existent profile."""
        with patch('sshaws.cli.boto3.Session') as mock_session:
            mock_session.side_effect = ProfileNotFound(profile='badprofile')
            with pytest.raises(SystemExit) as exc_info:
                SSHAWSClient(profile='badprofile')
            assert exc_info.value.code == 1

    def test_init_no_credentials(self):
        """Test initialization without credentials."""
        with patch('sshaws.cli.boto3.Session') as mock_session:
            mock_session.side_effect = NoCredentialsError()
            with pytest.raises(SystemExit) as exc_info:
                SSHAWSClient()
            assert exc_info.value.code == 1


class TestSSHAWSClientListInstances:
    """Tests for list_instances method."""

    def test_list_instances_ssm_only(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances
    ):
        """Test listing only SSM-enabled instances."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        client = SSHAWSClient()
        instances = client.list_instances(show_all=False)

        assert len(instances) == 2
        instance_ids = [i['instance_id'] for i in instances]
        assert 'i-1234567890abcdef0' in instance_ids
        assert 'i-notags1234567890' in instance_ids
        assert 'i-0987654321fedcba0' not in instance_ids

    def test_list_instances_all(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances
    ):
        """Test listing all instances."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        client = SSHAWSClient()
        instances = client.list_instances(show_all=True)

        assert len(instances) == 3
        instance_ids = [i['instance_id'] for i in instances]
        assert 'i-terminated12345678' not in instance_ids

    def test_list_instances_sorted_by_ssm(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances
    ):
        """Test that instances are sorted with SSM-available first."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        client = SSHAWSClient()
        instances = client.list_instances(show_all=True)

        assert instances[0]['ssm_available'] is True

    def test_list_instances_client_error(self, mock_boto3_session):
        """Test handling of ClientError."""
        mock_boto3_session['ssm'].describe_instance_information.side_effect = (
            ClientError(
                {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
                'DescribeInstanceInformation'
            )
        )

        client = SSHAWSClient()
        instances = client.list_instances()

        assert instances == []

    def test_list_instances_no_tags(self, mock_boto3_session, sample_ssm_instances):
        """Test instance with no Name tag."""
        ec2_response = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-notags1234567890',
                    'State': {'Name': 'running'},
                    'PrivateIpAddress': '10.0.1.102'
                }]
            }]
        }
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = ec2_response

        client = SSHAWSClient()
        instances = client.list_instances(show_all=True)

        assert instances[0]['name'] == '-'


class TestSSHAWSClientGetDefaultUser:
    """Tests for get_default_user method."""

    def test_get_default_user_amazon_linux(self, mock_boto3_session):
        """Test default user for Amazon Linux."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PlatformName': 'Amazon Linux'}]
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'ec2-user'

    def test_get_default_user_ubuntu(self, mock_boto3_session):
        """Test default user for Ubuntu."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PlatformName': 'Ubuntu Server 20.04'}]
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'ubuntu'

    def test_get_default_user_debian(self, mock_boto3_session):
        """Test default user for Debian."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PlatformName': 'Debian GNU/Linux'}]
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'admin'

    def test_get_default_user_centos(self, mock_boto3_session):
        """Test default user for CentOS."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PlatformName': 'CentOS Linux'}]
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'centos'

    def test_get_default_user_rhel(self, mock_boto3_session):
        """Test default user for RHEL."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PlatformName': 'Red Hat Enterprise Linux'}]
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'ec2-user'

    def test_get_default_user_not_found(self, mock_boto3_session):
        """Test default user when instance not found."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': []
        }

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'ec2-user'

    def test_get_default_user_client_error(self, mock_boto3_session):
        """Test default user on ClientError."""
        mock_boto3_session['ssm'].describe_instance_information.side_effect = (
            ClientError(
                {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
                'DescribeInstanceInformation'
            )
        )

        client = SSHAWSClient()
        user = client.get_default_user('i-1234567890abcdef0')

        assert user == 'ec2-user'


class TestSSHAWSClientCheckSSMAvailable:
    """Tests for check_ssm_available method."""

    def test_check_ssm_online(self, mock_boto3_session):
        """Test SSM check for online instance."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        client = SSHAWSClient()
        available, status = client.check_ssm_available('i-1234567890abcdef0')

        assert available is True
        assert status == 'Online'

    def test_check_ssm_offline(self, mock_boto3_session):
        """Test SSM check for offline instance."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Offline'}]
        }

        client = SSHAWSClient()
        available, status = client.check_ssm_available('i-1234567890abcdef0')

        assert available is False
        assert 'Offline' in status

    def test_check_ssm_not_found(self, mock_boto3_session):
        """Test SSM check for non-existent instance."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': []
        }

        client = SSHAWSClient()
        available, status = client.check_ssm_available('i-1234567890abcdef0')

        assert available is False
        assert 'not found' in status.lower()

    def test_check_ssm_client_error(self, mock_boto3_session):
        """Test SSM check on ClientError."""
        mock_boto3_session['ssm'].describe_instance_information.side_effect = (
            ClientError(
                {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}},
                'DescribeInstanceInformation'
            )
        )

        client = SSHAWSClient()
        available, status = client.check_ssm_available('i-1234567890abcdef0')

        assert available is False
        assert 'AccessDenied' in status or 'Access Denied' in status


class TestSSHAWSClientBuildSSHCommand:
    """Tests for build_ssh_command method."""

    def test_build_basic_command(self, mock_boto3_session):
        """Test building basic SSH command."""
        client = SSHAWSClient()
        opts = SSHOptions()
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert cmd[0] == 'ssh'
        assert 'ec2-user@i-1234567890abcdef0' in cmd
        assert any('ProxyCommand' in arg for arg in cmd)

    def test_build_command_with_identity_file(self, mock_boto3_session):
        """Test building SSH command with identity file."""
        client = SSHAWSClient()
        opts = SSHOptions(identity_file='/path/to/key.pem')
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-i' in cmd
        idx = cmd.index('-i')
        assert cmd[idx + 1] == '/path/to/key.pem'

    def test_build_command_with_port(self, mock_boto3_session):
        """Test building SSH command with non-default port."""
        client = SSHAWSClient()
        opts = SSHOptions(port=2222)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-p' in cmd
        idx = cmd.index('-p')
        assert cmd[idx + 1] == '2222'

    def test_build_command_with_local_forwards(self, mock_boto3_session):
        """Test building SSH command with local port forwards."""
        client = SSHAWSClient()
        forwarding = ForwardingOptions(
            local=['8080:localhost:80', '3306:localhost:3306']
        )
        opts = SSHOptions(forwarding=forwarding)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert cmd.count('-L') == 2
        assert '8080:localhost:80' in cmd
        assert '3306:localhost:3306' in cmd

    def test_build_command_with_remote_forwards(self, mock_boto3_session):
        """Test building SSH command with remote port forwards."""
        client = SSHAWSClient()
        forwarding = ForwardingOptions(remote=['9000:localhost:9000'])
        opts = SSHOptions(forwarding=forwarding)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-R' in cmd
        assert '9000:localhost:9000' in cmd

    def test_build_command_with_dynamic_forward(self, mock_boto3_session):
        """Test building SSH command with dynamic forward."""
        client = SSHAWSClient()
        forwarding = ForwardingOptions(dynamic='1080')
        opts = SSHOptions(forwarding=forwarding)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-D' in cmd
        assert '1080' in cmd

    def test_build_command_with_verbose(self, mock_boto3_session):
        """Test building SSH command with verbose flags."""
        client = SSHAWSClient()
        terminal = TerminalOptions(verbose=2)
        opts = SSHOptions(terminal=terminal)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-vv' in cmd

    def test_build_command_verbose_max_three(self, mock_boto3_session):
        """Test that verbose is capped at 3."""
        client = SSHAWSClient()
        terminal = TerminalOptions(verbose=5)
        opts = SSHOptions(terminal=terminal)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-vvv' in cmd
        assert '-vvvvv' not in cmd

    def test_build_command_with_no_tty(self, mock_boto3_session):
        """Test building SSH command with no TTY."""
        client = SSHAWSClient()
        terminal = TerminalOptions(no_tty=True)
        opts = SSHOptions(terminal=terminal)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-T' in cmd

    def test_build_command_with_force_tty(self, mock_boto3_session):
        """Test building SSH command with force TTY."""
        client = SSHAWSClient()
        terminal = TerminalOptions(force_tty=True)
        opts = SSHOptions(terminal=terminal)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-t' in cmd

    def test_build_command_with_no_command(self, mock_boto3_session):
        """Test building SSH command with no remote command."""
        client = SSHAWSClient()
        terminal = TerminalOptions(no_command=True)
        opts = SSHOptions(terminal=terminal)
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert '-N' in cmd

    def test_build_command_with_options(self, mock_boto3_session):
        """Test building SSH command with extra options."""
        client = SSHAWSClient()
        opts = SSHOptions(extra_options=['BatchMode=yes', 'ConnectTimeout=10'])
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert cmd.count('-o') >= 2

    def test_build_command_with_remote_command(self, mock_boto3_session):
        """Test building SSH command with remote command."""
        client = SSHAWSClient()
        opts = SSHOptions(remote_command=['uname', '-a'])
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        assert 'uname' in cmd
        assert '-a' in cmd

    def test_build_command_with_profile(self, mock_boto3_session):
        """Test building SSH command includes profile in ProxyCommand."""
        mock_boto3_session['session'].profile_name = 'myprofile'
        client = SSHAWSClient(profile='myprofile')
        opts = SSHOptions()
        cmd = client.build_ssh_command('i-1234567890abcdef0', 'ec2-user', opts)

        proxy_cmd = next(arg for arg in cmd if 'ProxyCommand' in arg)
        assert '--profile' in proxy_cmd
        assert 'myprofile' in proxy_cmd


class TestSSHAWSClientConnect:
    """Tests for connect method."""

    def test_connect_success(self, mock_boto3_session):
        """Test successful connection."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch('sshaws.cli.subprocess.call') as mock_call:
            mock_call.return_value = 0
            client = SSHAWSClient()
            opts = SSHOptions()
            result = client.connect('i-1234567890abcdef0', 'ec2-user', opts)

            assert result == 0
            mock_call.assert_called_once()

    def test_connect_ssm_unavailable(self, mock_boto3_session):
        """Test connection when SSM is unavailable."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': []
        }

        client = SSHAWSClient()
        opts = SSHOptions()
        result = client.connect('i-1234567890abcdef0', 'ec2-user', opts)

        assert result == 1

    def test_connect_verbose(self, mock_boto3_session, capsys):
        """Test connection with verbose output."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch('sshaws.cli.subprocess.call') as mock_call:
            mock_call.return_value = 0
            client = SSHAWSClient()
            terminal = TerminalOptions(verbose=1)
            opts = SSHOptions(terminal=terminal)
            client.connect('i-1234567890abcdef0', 'ec2-user', opts)

            captured = capsys.readouterr()
            assert 'Executing:' in captured.err


class TestSSHAWSClientStartSSMSession:
    """Tests for start_ssm_session method."""

    def test_start_ssm_session(self, mock_boto3_session):
        """Test starting direct SSM session."""
        with patch('sshaws.cli.subprocess.call') as mock_call:
            mock_call.return_value = 0
            client = SSHAWSClient()
            result = client.start_ssm_session('i-1234567890abcdef0')

            assert result == 0
            mock_call.assert_called_once()
            call_args = mock_call.call_args[0][0]
            assert 'aws' in call_args
            assert 'ssm' in call_args
            assert 'start-session' in call_args

    def test_start_ssm_session_with_profile(self, mock_boto3_session):
        """Test SSM session includes profile."""
        mock_boto3_session['session'].profile_name = 'myprofile'

        with patch('sshaws.cli.subprocess.call') as mock_call:
            mock_call.return_value = 0
            client = SSHAWSClient(profile='myprofile')
            client.start_ssm_session('i-1234567890abcdef0')

            call_args = mock_call.call_args[0][0]
            assert '--profile' in call_args
            assert 'myprofile' in call_args


class TestSSHAWSClientRunSSMCommand:
    """Tests for run_ssm_command method."""

    def test_run_command_success(self, mock_boto3_session, capsys):
        """Test successful command execution with stdout."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': 'Linux\n',
            'StandardErrorContent': '',
        }

        client = SSHAWSClient()
        result = client.run_ssm_command('i-1234567890abcdef0', ['uname'])

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == 'Linux\n'

    def test_run_command_with_stderr(self, mock_boto3_session, capsys):
        """Test command execution with stderr output."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Failed',
            'StandardOutputContent': '',
            'StandardErrorContent': 'command not found\n',
        }

        client = SSHAWSClient()
        result = client.run_ssm_command('i-1234567890abcdef0', ['badcmd'])

        assert result == 1
        captured = capsys.readouterr()
        assert 'command not found' in captured.err

    def test_run_command_send_error(self, mock_boto3_session, capsys):
        """Test ClientError from send_command."""
        mock_boto3_session['ssm'].send_command.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
            'SendCommand'
        )

        client = SSHAWSClient()
        result = client.run_ssm_command('i-1234567890abcdef0', ['uname'])

        assert result == 1
        captured = capsys.readouterr()
        assert 'Error sending command' in captured.err

    def test_run_command_poll_retry(self, mock_boto3_session, capsys):
        """Test polling retries when invocation not yet available."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        # First call raises, second call returns result
        mock_boto3_session['ssm'].get_command_invocation.side_effect = [
            ClientError(
                {'Error': {'Code': 'InvocationDoesNotExist', 'Message': ''}},
                'GetCommandInvocation'
            ),
            {
                'Status': 'Success',
                'StandardOutputContent': 'done\n',
                'StandardErrorContent': '',
            },
        ]

        with patch('sshaws.cli.time.sleep'):
            client = SSHAWSClient()
            result = client.run_ssm_command('i-1234567890abcdef0', ['echo', 'done'])

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == 'done\n'

    def test_run_command_timeout(self, mock_boto3_session, capsys):
        """Test timeout when polling never returns terminal status."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'InProgress',
            'StandardOutputContent': '',
            'StandardErrorContent': '',
        }

        with patch('sshaws.cli.time.sleep'):
            client = SSHAWSClient()
            result = client.run_ssm_command('i-1234567890abcdef0', ['sleep', '999'])

        assert result == 1
        captured = capsys.readouterr()
        assert 'Timed out' in captured.err

    def test_run_command_joins_args(self, mock_boto3_session):
        """Test that command list is joined with spaces."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': '',
            'StandardErrorContent': '',
        }

        with patch('sshaws.cli.time.sleep'):
            client = SSHAWSClient()
            client.run_ssm_command('i-1234567890abcdef0', ['uname', '-a'])

        call_kwargs = mock_boto3_session['ssm'].send_command.call_args
        assert call_kwargs[1]['Parameters']['commands'] == ['uname -a']

    def test_run_command_with_stdin(self, mock_boto3_session, capsys):
        """Test command with stdin data uses heredoc."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': '{"msg": "ok"}\n',
            'StandardErrorContent': '',
        }

        with patch('sshaws.cli.time.sleep'):
            client = SSHAWSClient()
            result = client.run_ssm_command(
                'i-1234567890abcdef0', ['python3'],
                stdin_data='print("hello")'
            )

        assert result == 0
        call_kwargs = mock_boto3_session['ssm'].send_command.call_args
        commands = call_kwargs[1]['Parameters']['commands']
        assert commands[0] == "python3 << 'SSHAWS_EOF'"
        assert commands[1] == 'print("hello")'
        assert commands[2] == 'SSHAWS_EOF'

    def test_run_command_without_stdin(self, mock_boto3_session):
        """Test command without stdin data uses plain command."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': '',
            'StandardErrorContent': '',
        }

        with patch('sshaws.cli.time.sleep'):
            client = SSHAWSClient()
            client.run_ssm_command(
                'i-1234567890abcdef0', ['uname'], stdin_data=None
            )

        call_kwargs = mock_boto3_session['ssm'].send_command.call_args
        assert call_kwargs[1]['Parameters']['commands'] == ['uname']


class TestSSHAWSClientResolveInstanceId:
    """Tests for resolve_instance_id method."""

    def test_resolve_direct_instance_id(self, mock_boto3_session):
        """Instance ID passes through without API call."""
        client = SSHAWSClient()
        result = client.resolve_instance_id('i-1234567890abcdef0')
        assert result == 'i-1234567890abcdef0'
        mock_boto3_session['ec2'].describe_instances.assert_not_called()

    def test_resolve_by_private_ip(self, mock_boto3_session):
        """Private IP resolves to instance ID."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-1234567890abcdef0',
                    'PrivateIpAddress': '10.0.1.100',
                    'Tags': [{'Key': 'Name', 'Value': 'web-server'}]
                }]
            }]
        }
        client = SSHAWSClient()
        result = client.resolve_instance_id('10.0.1.100')
        assert result == 'i-1234567890abcdef0'

    def test_resolve_by_private_ip_no_match(self, mock_boto3_session):
        """Private IP with no match exits."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': []
        }
        client = SSHAWSClient()
        with pytest.raises(SystemExit) as exc_info:
            client.resolve_instance_id('10.0.99.99')
        assert exc_info.value.code == 1

    def test_resolve_by_private_ip_multiple(self, mock_boto3_session, capsys):
        """Private IP with multiple matches lists them."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [
                    {
                        'InstanceId': 'i-aaa1111111111111a',
                        'Tags': [{'Key': 'Name', 'Value': 'host-a'}]
                    },
                    {
                        'InstanceId': 'i-bbb2222222222222b',
                        'Tags': [{'Key': 'Name', 'Value': 'host-b'}]
                    },
                ]
            }]
        }
        client = SSHAWSClient()
        with pytest.raises(SystemExit):
            client.resolve_instance_id('10.0.1.100')
        captured = capsys.readouterr()
        assert 'Multiple instances' in captured.err
        assert 'i-aaa1111111111111a' in captured.err
        assert 'i-bbb2222222222222b' in captured.err

    def test_resolve_by_name(self, mock_boto3_session):
        """Name tag resolves to instance ID."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-1234567890abcdef0',
                    'PrivateIpAddress': '10.0.1.100',
                    'Tags': [{'Key': 'Name', 'Value': 'web-server'}]
                }]
            }]
        }
        client = SSHAWSClient()
        result = client.resolve_instance_id('web-server')
        assert result == 'i-1234567890abcdef0'

    def test_resolve_by_name_no_match(self, mock_boto3_session, capsys):
        """Name tag with no match exits."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': []
        }
        client = SSHAWSClient()
        with pytest.raises(SystemExit) as exc_info:
            client.resolve_instance_id('nonexistent-server')
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert 'No instance found with Name tag' in captured.err

    def test_resolve_by_name_multiple(self, mock_boto3_session, capsys):
        """Name tag with multiple matches lists them."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [
                    {
                        'InstanceId': 'i-aaa1111111111111a',
                        'PrivateIpAddress': '10.0.1.100',
                    },
                    {
                        'InstanceId': 'i-bbb2222222222222b',
                        'PrivateIpAddress': '10.0.1.101',
                    },
                ]
            }]
        }
        client = SSHAWSClient()
        with pytest.raises(SystemExit):
            client.resolve_instance_id('web-server')
        captured = capsys.readouterr()
        assert 'Multiple instances' in captured.err
        assert 'disambiguate' in captured.err.lower()

    def test_resolve_by_private_ip_client_error(self, mock_boto3_session, capsys):
        """EC2 API error during IP resolution."""
        mock_boto3_session['ec2'].describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
            'DescribeInstances'
        )
        client = SSHAWSClient()
        with pytest.raises(SystemExit):
            client.resolve_instance_id('10.0.1.100')
        captured = capsys.readouterr()
        assert 'Error querying EC2' in captured.err

    def test_resolve_by_name_client_error(self, mock_boto3_session, capsys):
        """EC2 API error during name resolution."""
        mock_boto3_session['ec2'].describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
            'DescribeInstances'
        )
        client = SSHAWSClient()
        with pytest.raises(SystemExit):
            client.resolve_instance_id('web-server')
        captured = capsys.readouterr()
        assert 'Error querying EC2' in captured.err


class TestParseDestination:
    """Tests for parse_destination function."""

    def test_parse_with_user(self):
        """Test parsing destination with user."""
        user, instance_id = parse_destination('ubuntu@i-1234567890abcdef0')
        assert user == 'ubuntu'
        assert instance_id == 'i-1234567890abcdef0'

    def test_parse_without_user(self):
        """Test parsing destination without user."""
        user, instance_id = parse_destination('i-1234567890abcdef0')
        assert user is None
        assert instance_id == 'i-1234567890abcdef0'

    def test_parse_with_at_in_user(self):
        """Test parsing destination with @ in user (edge case)."""
        user, instance_id = parse_destination('user@domain@i-1234567890abcdef0')
        assert user == 'user'
        assert instance_id == 'domain@i-1234567890abcdef0'

    def test_parse_with_name_tag(self):
        """Test parsing destination with Name tag."""
        user, target = parse_destination('ubuntu@web-server')
        assert user == 'ubuntu'
        assert target == 'web-server'

    def test_parse_with_ip_address(self):
        """Test parsing destination with IP address."""
        user, target = parse_destination('ubuntu@172.20.21.43')
        assert user == 'ubuntu'
        assert target == '172.20.21.43'

    def test_parse_name_without_user(self):
        """Test parsing Name tag without user."""
        user, target = parse_destination('web-server')
        assert user is None
        assert target == 'web-server'


class TestFormatInstanceList:
    """Tests for format_instance_list function."""

    def test_format_empty_list(self):
        """Test formatting empty instance list."""
        result = format_instance_list([])
        assert 'No instances found' in result

    def test_format_json(self):
        """Test JSON output format."""
        instances = [
            {'instance_id': 'i-123', 'name': 'test', 'state': 'running',
             'private_ip': '10.0.0.1', 'public_ip': '-', 'platform': 'Linux',
             'ssm_status': 'Online', 'ssm_available': True}
        ]
        result = format_instance_list(instances, output_format='json')
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]['instance_id'] == 'i-123'

    def test_format_simple(self):
        """Test simple output format."""
        instances = [
            {'instance_id': 'i-123', 'name': 'test', 'private_ip': '10.0.0.1',
             'ssm_available': True}
        ]
        result = format_instance_list(instances, output_format='simple')
        assert '✓' in result
        assert 'i-123' in result

    def test_format_simple_unavailable(self):
        """Test simple output format for unavailable instance."""
        instances = [
            {'instance_id': 'i-123', 'name': 'test', 'private_ip': '10.0.0.1',
             'ssm_available': False}
        ]
        result = format_instance_list(instances, output_format='simple')
        assert '✗' in result

    def test_format_table(self):
        """Test table output format."""
        instances = [
            {'instance_id': 'i-1234567890abcdef0', 'name': 'test-server',
             'state': 'running', 'private_ip': '10.0.0.1', 'platform': 'Linux',
             'ssm_available': True}
        ]
        result = format_instance_list(instances, output_format='table')
        assert 'Instance ID' in result
        assert 'i-1234567890abcdef0' in result

    def test_format_table_long_name_truncated(self):
        """Test that long names are truncated in table format."""
        instances = [
            {'instance_id': 'i-123', 'name': 'a' * 50, 'state': 'running',
             'private_ip': '10.0.0.1', 'platform': 'Linux', 'ssm_available': True}
        ]
        result = format_instance_list(instances, output_format='table')
        assert '…' in result


class TestParseListCommand:
    """Tests for parse_list_command function."""

    def test_parse_empty(self):
        """Test parsing empty args."""
        profile, region, show_all, output_format = parse_list_command([])
        assert profile is None
        assert region is None
        assert show_all is False
        assert output_format == 'table'

    def test_parse_profile_long(self):
        """Test parsing --profile."""
        profile, _, _, _ = parse_list_command(['--profile', 'myprofile'])
        assert profile == 'myprofile'

    def test_parse_profile_short(self):
        """Test parsing -P."""
        profile, _, _, _ = parse_list_command(['-P', 'myprofile'])
        assert profile == 'myprofile'

    def test_parse_profile_equals(self):
        """Test parsing --profile=value."""
        profile, _, _, _ = parse_list_command(['--profile=myprofile'])
        assert profile == 'myprofile'

    def test_parse_region(self):
        """Test parsing --region."""
        _, region, _, _ = parse_list_command(['--region', 'us-west-2'])
        assert region == 'us-west-2'

    def test_parse_region_equals(self):
        """Test parsing --region=value."""
        _, region, _, _ = parse_list_command(['--region=eu-west-1'])
        assert region == 'eu-west-1'

    def test_parse_all_short(self):
        """Test parsing -a."""
        _, _, show_all, _ = parse_list_command(['-a'])
        assert show_all is True

    def test_parse_all_long(self):
        """Test parsing --all."""
        _, _, show_all, _ = parse_list_command(['--all'])
        assert show_all is True

    def test_parse_output_short(self):
        """Test parsing -o."""
        _, _, _, output_format = parse_list_command(['-o', 'json'])
        assert output_format == 'json'

    def test_parse_output_long(self):
        """Test parsing --output."""
        _, _, _, output_format = parse_list_command(['--output', 'simple'])
        assert output_format == 'simple'

    def test_parse_output_equals(self):
        """Test parsing --output=value."""
        _, _, _, output_format = parse_list_command(['--output=json'])
        assert output_format == 'json'

    def test_parse_combined(self):
        """Test parsing multiple options."""
        profile, region, show_all, output_format = parse_list_command([
            '--profile', 'prod', '--region', 'us-east-1', '-a', '-o', 'json'
        ])
        assert profile == 'prod'
        assert region == 'us-east-1'
        assert show_all is True
        assert output_format == 'json'


class TestMain:
    """Tests for main function."""

    def test_main_no_args(self, capsys):
        """Test main with no arguments shows help."""
        with patch.object(sys, 'argv', ['sshaws']):
            result = main()
            assert result == 1
            captured = capsys.readouterr()
            assert 'usage' in captured.out.lower() or 'usage' in captured.err.lower()

    def test_main_list_command(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances, capsys
    ):
        """Test main with list command."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        with patch.object(sys, 'argv', ['sshaws', 'list']):
            result = main()
            assert result == 0
            captured = capsys.readouterr()
            assert 'Instance ID' in captured.out

    def test_main_list_with_options(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances, capsys
    ):
        """Test main with list command and options."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        with patch.object(
            sys, 'argv', ['sshaws', '--profile', 'test', 'list', '-o', 'json']
        ):
            result = main()
            assert result == 0
            captured = capsys.readouterr()
            parsed = json.loads(captured.out)
            assert isinstance(parsed, list)

    def test_main_resolve_name_not_found(self, mock_boto3_session, capsys):
        """Test main with Name tag that matches no instances."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': []
        }

        with patch.object(sys, 'argv', ['sshaws', 'nonexistent-host']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert 'No instance found with Name tag' in captured.err

    def test_main_ssh_connection(self, mock_boto3_session):
        """Test main with SSH connection."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [
                {'PingStatus': 'Online', 'PlatformName': 'Amazon Linux'}
            ]
        }

        with patch.object(sys, 'argv', ['sshaws', 'i-1234567890abcdef0']):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0

    def test_main_ssh_with_user(self, mock_boto3_session):
        """Test main with user@instance format."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch.object(
            sys, 'argv', ['sshaws', 'ubuntu@i-1234567890abcdef0']
        ):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'ubuntu@i-1234567890abcdef0' in call_args

    def test_main_ssh_with_login_name(self, mock_boto3_session):
        """Test main with -l option."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch.object(
            sys, 'argv', ['sshaws', '-l', 'admin', 'i-1234567890abcdef0']
        ):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'admin@i-1234567890abcdef0' in call_args

    def test_main_ssm_mode(self, mock_boto3_session):
        """Test main with --ssm option."""
        with patch.object(
            sys, 'argv', ['sshaws', '--ssm', 'i-1234567890abcdef0']
        ):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'start-session' in call_args

    def test_main_with_all_options(self, mock_boto3_session):
        """Test main with all SSH options."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch.object(sys, 'argv', [
            'sshaws',
            '-i', '/path/to/key.pem',
            '-p', '2222',
            '-L', '8080:localhost:80',
            '-R', '9000:localhost:9000',
            '-D', '1080',
            '-N',
            '-T',
            '-v',
            '-o', 'BatchMode=yes',
            '--profile', 'prod',
            '--region', 'us-west-2',
            'ec2-user@i-1234567890abcdef0'
        ]):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0

    def test_main_with_remote_command(self, mock_boto3_session):
        """Test main with remote command."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch.object(
            sys, 'argv', ['sshaws', 'i-1234567890abcdef0', 'whoami']
        ):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'whoami' in call_args

    def test_main_list_with_profile_before_list(
        self, mock_boto3_session, sample_ec2_instances, sample_ssm_instances
    ):
        """Test list command with profile specified before 'list'."""
        mock_boto3_session['ssm'].describe_instance_information.return_value = (
            sample_ssm_instances
        )
        mock_boto3_session['ec2'].describe_instances.return_value = (
            sample_ec2_instances
        )

        with patch.object(sys, 'argv', ['sshaws', '-P', 'myprofile', 'list']):
            result = main()
            assert result == 0

    def test_main_ssh_by_name(self, mock_boto3_session):
        """Test SSH connection using Name tag."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-1234567890abcdef0',
                    'Tags': [{'Key': 'Name', 'Value': 'web-server'}]
                }]
            }]
        }
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [
                {'PingStatus': 'Online', 'PlatformName': 'Amazon Linux'}
            ]
        }

        with patch.object(sys, 'argv', ['sshaws', 'web-server']):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'ec2-user@i-1234567890abcdef0' in call_args

    def test_main_ssh_by_name_with_user(self, mock_boto3_session):
        """Test SSH connection using user@Name format."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-1234567890abcdef0',
                    'Tags': [{'Key': 'Name', 'Value': 'web-server'}]
                }]
            }]
        }
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [{'PingStatus': 'Online'}]
        }

        with patch.object(sys, 'argv', ['sshaws', 'ubuntu@web-server']):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'ubuntu@i-1234567890abcdef0' in call_args

    def test_main_ssh_by_private_ip(self, mock_boto3_session):
        """Test SSH connection using private IP."""
        mock_boto3_session['ec2'].describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{
                    'InstanceId': 'i-1234567890abcdef0',
                    'PrivateIpAddress': '172.20.21.43',
                }]
            }]
        }
        mock_boto3_session['ssm'].describe_instance_information.return_value = {
            'InstanceInformationList': [
                {'PingStatus': 'Online', 'PlatformName': 'Ubuntu'}
            ]
        }

        with patch.object(sys, 'argv', ['sshaws', 'ubuntu@172.20.21.43']):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'ubuntu@i-1234567890abcdef0' in call_args

    def test_main_ssm_mode_with_command(self, mock_boto3_session, capsys):
        """Test --ssm with a remote command uses send_command."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': 'Linux\n',
            'StandardErrorContent': '',
        }

        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        with patch.object(
            sys, 'argv', ['sshaws', '--ssm', 'i-1234567890abcdef0', 'uname']
        ):
            with patch('sshaws.cli.time.sleep'):
                with patch('sshaws.cli.sys.stdin', mock_stdin):
                    result = main()
                    assert result == 0

        mock_boto3_session['ssm'].send_command.assert_called_once()
        captured = capsys.readouterr()
        assert captured.out == 'Linux\n'

    def test_main_ssm_mode_without_command(self, mock_boto3_session):
        """Test --ssm without command still uses start-session."""
        with patch.object(
            sys, 'argv', ['sshaws', '--ssm', 'i-1234567890abcdef0']
        ):
            with patch('sshaws.cli.subprocess.call') as mock_call:
                mock_call.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_call.call_args[0][0]
                assert 'start-session' in call_args
        mock_boto3_session['ssm'].send_command.assert_not_called()

    def test_main_ssm_mode_with_stdin(self, mock_boto3_session, capsys):
        """Test --ssm with piped stdin uses heredoc in send_command."""
        mock_boto3_session['ssm'].send_command.return_value = {
            'Command': {'CommandId': 'cmd-123'}
        }
        mock_boto3_session['ssm'].get_command_invocation.return_value = {
            'Status': 'Success',
            'StandardOutputContent': '{"changed": true}\n',
            'StandardErrorContent': '',
        }

        from io import StringIO
        fake_stdin = StringIO('import json; print(json.dumps({"changed": True}))')

        with patch.object(sys, 'argv', [
            'sshaws', '--ssm', 'i-1234567890abcdef0', 'python3'
        ]):
            with patch('sshaws.cli.time.sleep'):
                with patch('sshaws.cli.sys.stdin', fake_stdin):
                    result = main()

        assert result == 0
        call_kwargs = mock_boto3_session['ssm'].send_command.call_args
        commands = call_kwargs[1]['Parameters']['commands']
        assert commands[0] == "python3 << 'SSHAWS_EOF'"
        assert commands[2] == 'SSHAWS_EOF'
