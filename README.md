# sshaws

SSH to private AWS EC2 instances via SSM. Drop-in replacement for `ssh` when connecting to EC2 instances.

## Features

- **SSH-like CLI** - Familiar interface: `sshaws user@i-xxx`
- **Multi-session support** - Single container, multiple concurrent SSH sessions
- **No bastion needed** - Connect through AWS SSM service
- **No public IP required** - Works with fully private instances  
- **Port forwarding** - Local (`-L`), remote (`-R`), and SOCKS (`-D`)
- **Identity files** - Standard `-i` option for SSH keys
- **Instance listing** - Built-in `list` subcommand

## Quick Start

### Install

```bash
# Extract
tar -xzf sshaws.tar.gz
cd sshaws

# Run setup (builds Docker image and installs wrapper)
./setup.sh

# Or install to ~/.local/bin instead of /usr/local/bin
./setup.sh --user
```

### Connect

```bash
# List available instances
sshaws list

# SSH to instance (container auto-starts)
sshaws i-0123456789abcdef0

# Open another terminal, start another session (reuses same container)
sshaws ubuntu@i-0987654321fedcba0

# Check active sessions
sshaws status

# Stop container when done
sshaws stop
```

### Update / Reinstall

The setup script is idempotent - run it again anytime to rebuild:

```bash
./setup.sh
```

### Uninstall

```bash
./setup.sh --uninstall
```

## Multi-Session Support

The tool uses a persistent Docker container that stays running, allowing multiple SSH sessions from different terminals:

```bash
# Terminal 1: Start first SSH session
sshaws ec2-user@i-0123456789abcdef0

# Terminal 2: Start second SSH session (reuses container)
sshaws ubuntu@i-0987654321fedcba0

# Terminal 3: Port forwarding (reuses container)
sshaws -L 3306:localhost:3306 -N i-0123456789abcdef0

# Terminal 4: Check status
sshaws status
# Output:
#   Status: Running
#   Active sessions: 3 active SSH/SSM session(s)
```

## Management Commands

| Command | Description |
|---------|-------------|
| `sshaws start` | Start the persistent container |
| `sshaws stop` | Stop the container |
| `sshaws restart` | Restart the container |
| `sshaws status` | Show container and session status |

## Setup Script Options

| Option | Description |
|--------|-------------|
| `./setup.sh` | Build image and install to `/usr/local/bin` |
| `./setup.sh --user` | Install to `~/.local/bin` (no sudo) |
| `./setup.sh --build-only` | Only build Docker image |
| `./setup.sh --uninstall` | Remove sshaws completely |

## Usage

```
sshaws [OPTIONS] [user@]<instance-id> [COMMAND]
sshaws list [OPTIONS]
```

### SSH Options

| Option | Description |
|--------|-------------|
| `-i FILE` | Identity file (private key) |
| `-l USER` | Login user name |
| `-p PORT` | Port (default: 22) |
| `-L [bind:]port:host:hostport` | Local port forward |
| `-R [bind:]port:host:hostport` | Remote port forward |
| `-D [bind:]port` | Dynamic SOCKS proxy |
| `-N` | No remote command (for tunnels) |
| `-T` | Disable TTY |
| `-t` | Force TTY |
| `-v` | Verbose (repeat for more) |
| `-o option` | SSH option |
| `--ssm` | Direct SSM session (no SSH) |
| `-P, --profile NAME` | AWS profile |
| `--region REGION` | AWS region |

### List Options

| Option | Description |
|--------|-------------|
| `-a, --all` | Show all instances, not just SSM-enabled |
| `-o, --output FORMAT` | Output format: table, json, simple |

## Examples

### Basic Connection

```bash
# Auto-detect user (ec2-user for Amazon Linux)
sshaws i-0123456789abcdef0

# Specify user
sshaws ubuntu@i-0123456789abcdef0

# With identity file
sshaws -i ~/.ssh/prod-key.pem ec2-user@i-0123456789abcdef0
```

### Port Forwarding

```bash
# Local forward: access remote MySQL on localhost:3306
sshaws -L 3306:localhost:3306 -N i-0123456789abcdef0

# Local forward: access remote web on localhost:8080
sshaws -L 8080:localhost:80 -N i-0123456789abcdef0

# Access RDS through EC2 instance
sshaws -L 5432:my-rds.xxx.us-east-1.rds.amazonaws.com:5432 -N i-xxx

# SOCKS proxy
sshaws -D 1080 -N i-0123456789abcdef0
# Then configure browser to use SOCKS5 proxy localhost:1080
```

### Remote Commands

```bash
# Run single command
sshaws i-0123456789abcdef0 uname -a

# Run command with arguments
sshaws i-0123456789abcdef0 df -h

# Interactive command
sshaws -t i-0123456789abcdef0 top
```

### List Instances

```bash
# List SSM-enabled instances
sshaws list

# Output:
# SSM  Instance ID          Name                         State      Private IP      Platform
# ------------------------------------------------------------------------------------------------
# ✓    i-0123456789abcdef0  web-server-prod              running    10.0.1.50       Linux
# ✓    i-0fedcba987654321f  api-server-prod              running    10.0.1.51       Linux
# ✗    i-0111111111111111a  database-server              running    10.0.2.10       Linux

# List all instances (including non-SSM)
sshaws list --all

# JSON output
sshaws list -o json

# Simple output (for scripting)
sshaws list -o simple
```

### AWS Profile & Region

```bash
# Use specific profile
sshaws --profile production list
sshaws -P production i-0123456789abcdef0

# Use specific region
sshaws --region us-west-2 list

# Environment variables also work
AWS_PROFILE=production sshaws list
```

### Direct SSM Session

```bash
# SSM session without SSH (uses SSM shell)
sshaws --ssm i-0123456789abcdef0
```

## Docker Usage (without wrapper)

```bash
# Start persistent container
docker run -d --name sshaws \
  -v ~/.aws:/root/.aws:ro \
  -v ~/.ssh:/root/.ssh:ro \
  --network host \
  --restart unless-stopped \
  sshaws

# List instances
docker exec -it sshaws sshaws list

# SSH connection (Terminal 1)
docker exec -it sshaws sshaws ec2-user@i-0123456789abcdef0

# Another SSH connection (Terminal 2 - same container)
docker exec -it sshaws sshaws ubuntu@i-0987654321fedcba0

# Port forwarding
docker exec -it sshaws sshaws -L 3306:localhost:3306 -N i-xxx

# Stop container
docker stop sshaws && docker rm sshaws
```

## Prerequisites

### Local Machine

- Docker
- AWS credentials (`~/.aws/credentials` or environment variables)

### EC2 Instance

1. **SSM Agent running** (pre-installed on Amazon Linux 2/2023, Ubuntu 18.04+)
   ```bash
   # Check status
   sudo systemctl status amazon-ssm-agent
   ```

2. **IAM Instance Profile** with SSM permissions:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": [
         "ssm:UpdateInstanceInformation",
         "ssmmessages:CreateControlChannel",
         "ssmmessages:CreateDataChannel",
         "ssmmessages:OpenControlChannel",
         "ssmmessages:OpenDataChannel"
       ],
       "Resource": "*"
     }]
   }
   ```
   Or attach the managed policy: `AmazonSSMManagedInstanceCore`

3. **Network connectivity to SSM** (one of):
   - Internet access via NAT Gateway
   - VPC Endpoints for SSM (ssm, ssmmessages, ec2messages)

### IAM User Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ssm:StartSession",
      "ssm:TerminateSession",
      "ssm:DescribeInstanceInformation",
      "ec2:DescribeInstances"
    ],
    "Resource": "*"
  }]
}
```

## Troubleshooting

### "Instance not found in SSM"

- Verify SSM agent is running: `systemctl status amazon-ssm-agent`
- Check instance has IAM role with SSM permissions
- Ensure network path to SSM endpoints exists

### "Permission denied (publickey)"

- Verify SSH key matches the one on the instance
- Check username (ubuntu, ec2-user, centos, etc.)
- Key file permissions: `chmod 600 ~/.ssh/mykey.pem`

### Connection timeout

- Check Security Groups allow outbound HTTPS (443)
- Verify VPC endpoints or NAT gateway configuration
- Try `sshaws --ssm i-xxx` to test SSM connectivity directly

### Verbose output

```bash
sshaws -vvv i-0123456789abcdef0
```

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Local Machine                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │ Terminal 1  │  │ Terminal 2  │  │ Terminal 3  │                  │
│  │ sshaws i-A  │  │ sshaws i-B  │  │ sshaws -L.. │                  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │
│         │                │                │                         │
│         └────────────────┼────────────────┘                         │
│                          ▼                                          │
│              ┌───────────────────────┐                              │
│              │   Docker Container    │                              │
│              │  (sshaws - persistent)│                              │
│              │   ┌─────┐ ┌─────┐    │                              │
│              │   │SSH 1│ │SSH 2│... │                              │
│              │   └─────┘ └─────┘    │                              │
│              └───────────┬───────────┘                              │
└──────────────────────────┼──────────────────────────────────────────┘
                           │ HTTPS (443)
                           ▼
                 ┌─────────────────────┐
                 │    AWS SSM Service  │
                 └──────────┬──────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ EC2 i-A  │  │ EC2 i-B  │  │ EC2 i-C  │
        │ (private)│  │ (private)│  │ (private)│
        └──────────┘  └──────────┘  └──────────┘
```

**Multi-session architecture:**
- Single persistent Docker container runs continuously
- Each `sshaws` command uses `docker exec` to run in the same container
- Multiple SSH sessions share container resources efficiently
- Container auto-starts on first use, stays running for subsequent sessions

## License

MIT
