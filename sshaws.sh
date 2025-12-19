#!/bin/bash
#
# sshaws - SSH to AWS EC2 instances via SSM (Docker wrapper)
#
# Supports multiple concurrent SSH sessions through a single persistent container.
#
# Installation:
#   1. Build: docker build -t sshaws /path/to/sshaws
#   2. Copy this script to your PATH: sudo cp sshaws.sh /usr/local/bin/sshaws
#   3. Make executable: sudo chmod +x /usr/local/bin/sshaws
#
# Management commands:
#   sshaws start   - Start the persistent container
#   sshaws stop    - Stop the container
#   sshaws status  - Check container status
#   sshaws restart - Restart the container
#

set -e

IMAGE_NAME="${SSHAWS_IMAGE:-sshaws:latest}"
CONTAINER_NAME="${SSHAWS_CONTAINER:-sshaws}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[sshaws]${NC} $1"
}

print_error() {
    echo -e "${RED}[sshaws]${NC} $1" >&2
}

print_warn() {
    echo -e "${YELLOW}[sshaws]${NC} $1"
}

# Check if Docker image exists
check_image() {
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        print_error "Docker image '$IMAGE_NAME' not found."
        print_error "Build it first: docker build -t sshaws /path/to/sshaws"
        exit 1
    fi
}

# Check if container is running
is_running() {
    docker ps --filter "name=^${CONTAINER_NAME}$" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"
}

# Check if container exists (running or stopped)
container_exists() {
    docker ps -a --filter "name=^${CONTAINER_NAME}$" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"
}

# Start the persistent container
start_container() {
    check_image
    
    if is_running; then
        print_warn "Container '$CONTAINER_NAME' is already running"
        return 0
    fi
    
    # Remove stopped container if exists
    if container_exists; then
        docker rm "$CONTAINER_NAME" >/dev/null 2>&1
    fi
    
    print_status "Starting sshaws container..."
    
    DOCKER_ARGS=(
        run -d
        --name "$CONTAINER_NAME"
        --network host
        --restart unless-stopped
        -v "${AWS_SHARED_CREDENTIALS_FILE:-$HOME/.aws}:/root/.aws:ro"
    )
    
    # Mount SSH keys directory if it exists
    if [[ -d "$HOME/.ssh" ]]; then
        DOCKER_ARGS+=(-v "$HOME/.ssh:/root/.ssh:ro")
    fi
    
    # Pass through AWS environment variables
    [[ -n "$AWS_PROFILE" ]] && DOCKER_ARGS+=(-e "AWS_PROFILE=$AWS_PROFILE")
    [[ -n "$AWS_DEFAULT_REGION" ]] && DOCKER_ARGS+=(-e "AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION")
    [[ -n "$AWS_ACCESS_KEY_ID" ]] && DOCKER_ARGS+=(-e "AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID")
    [[ -n "$AWS_SECRET_ACCESS_KEY" ]] && DOCKER_ARGS+=(-e "AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY")
    [[ -n "$AWS_SESSION_TOKEN" ]] && DOCKER_ARGS+=(-e "AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN")
    
    docker "${DOCKER_ARGS[@]}" "$IMAGE_NAME" >/dev/null
    
    print_status "Container started. You can now run multiple SSH sessions."
}

# Stop the container
stop_container() {
    if ! is_running; then
        print_warn "Container '$CONTAINER_NAME' is not running"
        return 0
    fi
    
    print_status "Stopping sshaws container..."
    docker stop "$CONTAINER_NAME" >/dev/null
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    print_status "Container stopped"
}

# Restart container
restart_container() {
    stop_container
    start_container
}

# Show container status
show_status() {
    if is_running; then
        echo -e "Status: ${GREEN}Running${NC}"
        echo ""
        echo "Container info:"
        docker ps --filter "name=^${CONTAINER_NAME}$" --format "  ID: {{.ID}}\n  Image: {{.Image}}\n  Created: {{.CreatedAt}}\n  Status: {{.Status}}"
        echo ""
        echo "Active sessions:"
        # Count exec processes (SSH sessions)
        SESSION_COUNT=$(docker top "$CONTAINER_NAME" 2>/dev/null | grep -cE "ssh|session-manager" || echo "0")
        echo "  $SESSION_COUNT active SSH/SSM session(s)"
    else
        echo -e "Status: ${RED}Not running${NC}"
        echo ""
        echo "Start with: sshaws start"
    fi
}

# Ensure container is running before executing command
ensure_running() {
    if ! is_running; then
        start_container
    fi
}

# Execute sshaws command in the container
exec_sshaws() {
    ensure_running
    
    # Build exec command
    EXEC_ARGS=(-it)
    
    # Handle identity file path translation
    ARGS=()
    SKIP_NEXT=false
    KEY_FILES=()
    
    for arg in "$@"; do
        if $SKIP_NEXT; then
            # This is the path after -i, check if it's a file we need to copy
            if [[ -f "$arg" ]]; then
                REALPATH=$(realpath "$arg")
                BASENAME=$(basename "$arg")
                KEY_FILES+=("$REALPATH:/tmp/keys/$BASENAME")
                ARGS+=("/tmp/keys/$BASENAME")
            else
                ARGS+=("$arg")
            fi
            SKIP_NEXT=false
        elif [[ "$arg" == "-i" ]]; then
            ARGS+=("$arg")
            SKIP_NEXT=true
        else
            ARGS+=("$arg")
        fi
    done
    
    # Copy key files into the container if needed
    if [[ ${#KEY_FILES[@]} -gt 0 ]]; then
        docker exec "$CONTAINER_NAME" mkdir -p /tmp/keys 2>/dev/null || true
        for keyspec in "${KEY_FILES[@]}"; do
            SRC="${keyspec%%:*}"
            DST="${keyspec#*:}"
            docker cp "$SRC" "$CONTAINER_NAME:$DST" 2>/dev/null || true
            docker exec "$CONTAINER_NAME" chmod 600 "$DST" 2>/dev/null || true
        done
    fi
    
    # Execute the command
    exec docker exec "${EXEC_ARGS[@]}" "$CONTAINER_NAME" sshaws "${ARGS[@]}"
}

# Show help
show_help() {
    cat << 'EOF'
sshaws - SSH to AWS EC2 instances via SSM

MANAGEMENT COMMANDS:
    sshaws start              Start the persistent container
    sshaws stop               Stop the container  
    sshaws restart            Restart the container
    sshaws status             Show container and session status

SSH COMMANDS:
    sshaws list [OPTIONS]     List EC2 instances with SSM status
    sshaws [user@]<instance>  SSH to instance
    sshaws [OPTIONS] <instance> [COMMAND]

OPTIONS:
    -i FILE                   Identity file (private key)
    -l USER                   Login user name
    -p PORT                   Port (default: 22)
    -L [bind:]port:host:port  Local port forward
    -R [bind:]port:host:port  Remote port forward  
    -D [bind:]port            Dynamic SOCKS proxy
    -N                        No remote command (for tunnels)
    -v                        Verbose mode (repeat for more)
    -P, --profile NAME        AWS profile
    --region REGION           AWS region

EXAMPLES:
    # Start container (auto-starts on first use)
    sshaws start

    # List instances
    sshaws list

    # SSH to instance (can run multiple in different terminals)
    sshaws i-0123456789abcdef0
    sshaws ubuntu@i-0123456789abcdef0
    sshaws -i ~/.ssh/key.pem ec2-user@i-xxx

    # Port forwarding
    sshaws -L 3306:localhost:3306 -N i-xxx

    # Check active sessions
    sshaws status

    # Stop when done
    sshaws stop

MULTI-SESSION:
    The container stays running, allowing multiple SSH sessions from
    different terminals. Each 'sshaws' command runs in the same container.

ENVIRONMENT:
    SSHAWS_IMAGE       Docker image name (default: sshaws:latest)
    SSHAWS_CONTAINER   Container name (default: sshaws)
    AWS_PROFILE        AWS profile to use
    AWS_DEFAULT_REGION AWS region

EOF
}

# Main
case "${1:-}" in
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    restart)
        restart_container
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        show_help
        ;;
    "")
        show_help
        ;;
    *)
        exec_sshaws "$@"
        ;;
esac
