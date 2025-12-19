FROM python:3.11-slim

LABEL maintainer="sshaws"
LABEL description="SSH to private AWS EC2 instances via SSM"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    groff \
    less \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && cd /tmp && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip

# Install Session Manager Plugin
RUN curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" \
    -o /tmp/session-manager-plugin.deb \
    && dpkg -i /tmp/session-manager-plugin.deb \
    && rm /tmp/session-manager-plugin.deb

# Install Python dependencies
RUN pip install --no-cache-dir boto3

# Setup SSH directory
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Copy sshaws tool
COPY scripts/sshaws /usr/local/bin/sshaws
RUN chmod +x /usr/local/bin/sshaws

WORKDIR /root

# Default to sleep infinity for daemon mode - allows multiple exec sessions
CMD ["sleep", "infinity"]
