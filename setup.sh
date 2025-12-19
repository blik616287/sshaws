#!/bin/bash
#
# sshaws setup script
# 
# Builds the Docker image and installs the sshaws wrapper script.
# Safe to run multiple times (idempotent).
#
# Usage:
#   ./setup.sh              # Install to /usr/local/bin (requires sudo)
#   ./setup.sh --user       # Install to ~/.local/bin (no sudo needed)
#   ./setup.sh --uninstall  # Remove sshaws
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
IMAGE_NAME="${SSHAWS_IMAGE:-sshaws:latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Detect install location
get_install_path() {
    if [[ "$1" == "--user" ]]; then
        echo "$HOME/.local/bin"
    else
        echo "/usr/local/bin"
    fi
}

# Check prerequisites
check_prerequisites() {
    info "Checking prerequisites..."
    
    local missing=()
    
    if ! command -v docker &>/dev/null; then
        missing+=("docker")
    fi
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing required tools: ${missing[*]}"
        echo ""
        echo "Please install the missing tools and try again."
        exit 1
    fi
    
    # Check Docker is running
    if ! docker info &>/dev/null; then
        error "Docker is not running or you don't have permission to access it."
        echo ""
        echo "Try:"
        echo "  - Start Docker: sudo systemctl start docker"
        echo "  - Add yourself to docker group: sudo usermod -aG docker \$USER"
        exit 1
    fi
    
    ok "Prerequisites satisfied"
}

# Build Docker image
build_image() {
    info "Building Docker image: $IMAGE_NAME"
    
    if docker image inspect "$IMAGE_NAME" &>/dev/null; then
        warn "Image already exists. Rebuilding..."
    fi
    
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
    
    ok "Docker image built: $IMAGE_NAME"
}

# Install wrapper script
install_wrapper() {
    local install_path="$1"
    local target="$install_path/sshaws"
    
    info "Installing sshaws to $install_path"
    
    # Create directory if needed
    if [[ ! -d "$install_path" ]]; then
        if [[ "$install_path" == "$HOME/.local/bin" ]]; then
            mkdir -p "$install_path"
        else
            sudo mkdir -p "$install_path"
        fi
    fi
    
    # Install script
    if [[ "$install_path" == "$HOME/.local/bin" ]]; then
        cp "$SCRIPT_DIR/sshaws.sh" "$target"
        chmod +x "$target"
    else
        sudo cp "$SCRIPT_DIR/sshaws.sh" "$target"
        sudo chmod +x "$target"
    fi
    
    ok "Installed: $target"
    
    # Check if in PATH
    if ! echo "$PATH" | tr ':' '\n' | grep -q "^$install_path$"; then
        warn "$install_path is not in your PATH"
        echo ""
        echo "Add it to your shell profile:"
        echo "  echo 'export PATH=\"$install_path:\$PATH\"' >> ~/.bashrc"
        echo "  source ~/.bashrc"
        echo ""
    fi
}

# Uninstall
uninstall() {
    info "Uninstalling sshaws..."
    
    # Stop and remove container if running
    if docker ps -a --filter "name=^sshaws$" --format '{{.Names}}' | grep -q "^sshaws$"; then
        info "Stopping sshaws container..."
        docker stop sshaws 2>/dev/null || true
        docker rm sshaws 2>/dev/null || true
        ok "Container removed"
    fi
    
    # Remove image
    if docker image inspect "$IMAGE_NAME" &>/dev/null; then
        info "Removing Docker image..."
        docker rmi "$IMAGE_NAME" 2>/dev/null || true
        ok "Image removed"
    fi
    
    # Remove wrapper script
    local removed=false
    for path in /usr/local/bin/sshaws "$HOME/.local/bin/sshaws"; do
        if [[ -f "$path" ]]; then
            if [[ "$path" == /usr/local/bin/* ]]; then
                sudo rm -f "$path"
            else
                rm -f "$path"
            fi
            ok "Removed: $path"
            removed=true
        fi
    done
    
    if ! $removed; then
        warn "No wrapper script found to remove"
    fi
    
    ok "Uninstall complete"
}

# Verify installation
verify_install() {
    info "Verifying installation..."
    
    # Check image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        error "Docker image not found: $IMAGE_NAME"
        return 1
    fi
    
    # Check wrapper is accessible
    if ! command -v sshaws &>/dev/null; then
        warn "sshaws not found in PATH (may need to reload shell)"
    else
        ok "sshaws is available: $(command -v sshaws)"
    fi
    
    ok "Installation verified"
}

# Print usage
usage() {
    cat << EOF
sshaws Setup Script

Usage: $0 [OPTIONS]

OPTIONS:
    --user       Install to ~/.local/bin (no sudo required)
    --uninstall  Remove sshaws completely
    --build-only Only build Docker image, don't install wrapper
    --help       Show this help message

EXAMPLES:
    $0                  # Build and install to /usr/local/bin
    $0 --user           # Build and install to ~/.local/bin
    $0 --uninstall      # Remove everything
    $0 --build-only     # Just build the Docker image

ENVIRONMENT:
    SSHAWS_IMAGE    Docker image name (default: sshaws:latest)

EOF
}

# Main
main() {
    local user_install=false
    local build_only=false
    local install_path="/usr/local/bin"
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --user)
                user_install=true
                install_path="$HOME/.local/bin"
                shift
                ;;
            --uninstall)
                uninstall
                exit 0
                ;;
            --build-only)
                build_only=true
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    echo ""
    echo "╔════════════════════════════════════╗"
    echo "║         sshaws Setup               ║"
    echo "╚════════════════════════════════════╝"
    echo ""
    
    check_prerequisites
    build_image
    
    if ! $build_only; then
        install_wrapper "$install_path"
        verify_install
    fi
    
    echo ""
    echo "════════════════════════════════════════"
    ok "Setup complete!"
    echo ""
    echo "Quick start:"
    echo "  sshaws list                    # List SSM-enabled instances"
    echo "  sshaws i-0123456789abcdef0     # SSH to instance"
    echo "  sshaws status                  # Check active sessions"
    echo ""
    echo "For help:"
    echo "  sshaws --help"
    echo ""
}

main "$@"
