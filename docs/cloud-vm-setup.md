# Cloud VM Setup Guide

This guide walks you through deploying Remote Coder on a cloud virtual machine (AWS EC2, DigitalOcean, Google Cloud, etc.).

## Why Run on a Cloud VM?

Running Remote Coder on a cloud VM provides several benefits:

1. **Always available** - Your coding assistant runs 24/7 without keeping your local machine on
2. **Centralized project access** - All team members can work on the same repositories
3. **Consistent environment** - Same setup across all deployments
4. **Resource isolation** - Agent tasks don't consume local machine resources

## Recommended VM Specifications

### Minimum Specifications
- **CPU**: 2 vCPUs
- **RAM**: 4 GB
- **Storage**: 20 GB SSD
- **OS**: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS

### AWS EC2 Instance Types
- **t3.medium** or **t3.small** - Good balance of performance and cost
- **t4g.medium** (ARM-based) - Cost-effective alternative

### Other Cloud Providers
- **DigitalOcean**: Basic Droplet (2 vCPUs, 4 GB RAM)
- **Google Cloud**: e2-medium instance
- **Azure**: B2s instance

## Setup Steps

### 1. Launch and Access Your VM

```bash
# For AWS EC2
ssh -i your-key.pem ubuntu@your-vm-ip

# For other providers
ssh ubuntu@your-vm-ip
```

### 2. Install System Dependencies

```bash
# Update package lists
sudo apt update

# Install essential tools
sudo apt install -y git python3.11 python3.11-venv python3-pip curl

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 3. Clone the Repository

```bash
# Create projects directory
mkdir -p ~/projects
cd ~/projects

# Clone Remote Coder
git clone https://github.com/PeterShin23/remote-coder.git
cd remote-coder
```

### 4. Configure Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit environment file
nano .env
```

Set the following variables:

```bash
# Slack credentials
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-1-...
SLACK_ALLOWED_USER_ID=U0123456789

# GitHub token (for PR features)
GITHUB_TOKEN=ghp_...

# Optional: OpenRouter API key for Qwen agent
OPENROUTER_API_KEY=sk-or-...
```

### 5. Configure Projects

```bash
# Copy projects template
cp config/projects.yaml.example config/projects.yaml

# Edit projects configuration
nano config/projects.yaml
```

Example configuration:

```yaml
# Base directory for all projects
base_dir: /home/ubuntu/projects

projects:
  my-project:
    path: my-project
    default_agent: codex
    github:
      owner: your-github-username
      repo: my-project
      default_base_branch: main
```

### 6. Install Agent CLIs

You have two options for installing and configuring agent CLIs:

#### Option A: Manual Installation

Install each agent CLI you want to use:

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code
# or
pip install claude-code

# Authenticate Claude
claude
# Then in the interactive session, run: /login

# Codex
pip install codex-cli
# Follow authentication instructions

# Gemini Code Assist
pip install google-gemini-cli
# Follow authentication instructions
```

#### Option B: Use Setup Script (Coming in Phase 3)

A setup script will be available to automate CLI installation and authentication. This script will be located at `scripts/setup_remote_coder_clis.sh`.

### 7. Clone Your Project Repositories

```bash
# Navigate to projects directory
cd ~/projects

# Clone your project(s)
git clone git@github.com:your-org/your-project.git
```

Make sure your VM has SSH access to GitHub:

```bash
# Generate SSH key if needed
ssh-keygen -t ed25519 -C "your-email@example.com"

# Add public key to GitHub
cat ~/.ssh/id_ed25519.pub
# Copy output and add to https://github.com/settings/keys
```

### 8. Install Python Dependencies

```bash
cd ~/projects/remote-coder

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 9. Test the Installation

```bash
# Run Remote Coder daemon
uv run python -m src
```

You should see log output indicating the Slack connection is active.

Send a test message to your Slack bot to verify everything works:
- In a Slack channel mapped in `projects.yaml`, mention the bot: `@remote-coder help`
- Or send a direct message: `!help`

### 10. Set Up Daemon (Optional but Recommended)

To keep Remote Coder running even after you disconnect from SSH:

#### Option A: Using tmux

```bash
# Install tmux
sudo apt install -y tmux

# Start a new tmux session
tmux new -s remote-coder

# Run the daemon
cd ~/projects/remote-coder
uv run python -m src

# Detach from tmux: Press Ctrl+B, then D
# Reattach later: tmux attach -t remote-coder
```

#### Option B: Using systemd (Production)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/remote-coder.service
```

Add the following content:

```ini
[Unit]
Description=Remote Coder Slack Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/projects/remote-coder
Environment="PATH=/home/ubuntu/.local/bin:/home/ubuntu/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/.cargo/bin/uv run python -m src
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable remote-coder

# Start the service
sudo systemctl start remote-coder

# Check status
sudo systemctl status remote-coder

# View logs
sudo journalctl -u remote-coder -f
```

## Maintenance

### Updating Remote Coder

```bash
cd ~/projects/remote-coder
git pull origin main
uv pip install -e .

# If using systemd
sudo systemctl restart remote-coder
```

### Updating Agent CLIs

```bash
# Update Claude Code
npm update -g @anthropic-ai/claude-code

# Update Codex
pip install --upgrade codex-cli

# Update Gemini
pip install --upgrade google-gemini-cli

# Restart daemon
sudo systemctl restart remote-coder
```

### Monitoring Logs

```bash
# If using systemd
sudo journalctl -u remote-coder -f

# If using tmux
tmux attach -t remote-coder
```

### Managing Sessions

Use Remote Coder's built-in commands:

- `!status` - Check current session status
- `!agents` - List available agents
- `!purge` - Clear all sessions and cancel running tasks
- `!stop-all` - Stop all active sessions (coming in Phase 2)
- `!reload-config` - Reload configuration without restart (coming in Phase 2)

## Security Considerations

### 1. Firewall Configuration

Your VM doesn't need inbound ports open since Remote Coder uses Slack's WebSocket (Socket Mode). Only outbound HTTPS is required.

### 2. SSH Access

- Use SSH key authentication (disable password auth)
- Consider using a bastion host or VPN for access
- Restrict SSH access to your IP address if possible

### 3. Secrets Management

- Never commit `.env` or `config/projects.yaml` to version control
- Use environment variables for sensitive data
- Consider using cloud provider secrets managers (AWS Secrets Manager, Google Secret Manager, etc.)

### 4. GitHub Token Permissions

Use a fine-grained GitHub token with minimal permissions:
- Contents: Read and Write (for commits)
- Pull Requests: Read and Write (for PR management)
- Scope to specific repositories only

## Troubleshooting

### Daemon Won't Start

```bash
# Check Python version
python3 --version  # Should be 3.11+

# Check if ports are in use
sudo lsof -i :3000

# Verify environment variables
env | grep SLACK
```

### Agent Authentication Issues

```bash
# Test Claude authentication
claude --version
claude -p "ping"

# Test Codex
codex --version

# Check Gemini
gemini --version
```

### Git Push Failures

```bash
# Verify SSH access to GitHub
ssh -T git@github.com

# Check git configuration
git config --list

# Ensure git user is set
git config --global user.email "bot@example.com"
git config --global user.name "Remote Coder Bot"
```

### Out of Disk Space

```bash
# Check disk usage
df -h

# Clean up Docker if installed
docker system prune -a

# Clean up old Python caches
find ~/projects -type d -name __pycache__ -exec rm -rf {} +
find ~/projects -type d -name .pytest_cache -exec rm -rf {} +
```

## Cost Estimation

### AWS EC2 (t3.medium in us-east-1)
- **Instance**: ~$30/month
- **Storage (20 GB)**: ~$2/month
- **Data transfer**: ~$1/month (minimal for Slack/GitHub API)
- **Total**: ~$33/month

### DigitalOcean (Basic Droplet, 2 vCPUs, 4 GB)
- **Droplet**: $24/month
- **Storage included**: 80 GB SSD
- **Total**: $24/month

### Google Cloud (e2-medium)
- **Instance**: ~$25/month
- **Storage (20 GB)**: ~$2/month
- **Total**: ~$27/month

These costs are in addition to your agent subscription costs (Claude Pro, Codex, etc.).

## Next Steps

Once your VM is running:

1. Test with a simple task in Slack
2. Verify PR creation works
3. Try switching agents with `!use`
4. Set up monitoring/alerts for VM health
5. Configure backups for project repositories

For more information, see:
- [Usage Philosophy](usage-philosophy.md) - Understanding the subscription model
- [README](../README.md) - Full feature documentation
