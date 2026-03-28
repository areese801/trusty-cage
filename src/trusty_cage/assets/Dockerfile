FROM ubuntu:24.04

ARG PYTHON_VERSION=3.12

# Avoid interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive
ENV TRUSTY_CAGE=1

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    tmux \
    zsh \
    ripgrep \
    fd-find \
    fzf \
    tree \
    cloc \
    jq \
    htop \
    build-essential \
    iptables \
    sudo \
    ca-certificates \
    unzip \
    locales \
    # pyenv build dependencies
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libffi-dev \
    liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

# Set locale
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Install Node.js 22 LTS (required by Claude Code and LazyVim Mason)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Neovim v0.11.2 prebuilt (ARM64)
RUN curl -fsSL https://github.com/neovim/neovim/releases/download/v0.11.2/nvim-linux-arm64.tar.gz \
    | tar -xz -C /opt \
    && ln -s /opt/nvim-linux-arm64/bin/nvim /usr/local/bin/nvim

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Install cage-send messaging helper
COPY cage-send /usr/local/bin/cage-send
RUN chmod +x /usr/local/bin/cage-send

# Create non-root user (remove default ubuntu user that occupies UID/GID 1000)
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd -g 1000 trustycage \
    && useradd -m -u 1000 -g trustycage -s /usr/bin/zsh trustycage \
    && echo "trustycage ALL=(root) NOPASSWD: /usr/sbin/iptables, /usr/sbin/ip6tables" >> /etc/sudoers.d/trustycage

USER trustycage
WORKDIR /home/trustycage

# Install oh-my-zsh (non-interactive, don't modify .zshrc — dotfiles will handle that)
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

# Create default .zshrc (suppresses first-run wizard; dotfiles overwrite this if configured)
RUN echo 'export ZSH="$HOME/.oh-my-zsh"' > /home/trustycage/.zshrc \
    && echo 'ZSH_THEME="robbyrussell"' >> /home/trustycage/.zshrc \
    && echo 'plugins=(git)' >> /home/trustycage/.zshrc \
    && echo 'source $ZSH/oh-my-zsh.sh' >> /home/trustycage/.zshrc \
    && echo 'export PATH="$HOME/.pyenv/bin:$HOME/.pyenv/shims:$HOME/.local/bin:$PATH"' >> /home/trustycage/.zshrc \
    && echo 'alias vim=nvim' >> /home/trustycage/.zshrc \
    && echo 'alias vi=nvim' >> /home/trustycage/.zshrc

# Install pyenv + Python
ENV PYENV_ROOT="/home/trustycage/.pyenv"
ENV PATH="${PYENV_ROOT}/bin:${PYENV_ROOT}/shims:${PATH}"

RUN git clone --depth 1 https://github.com/pyenv/pyenv.git "${PYENV_ROOT}" \
    && pyenv install "${PYTHON_VERSION}" \
    && pyenv global "${PYTHON_VERSION}" \
    && pyenv rehash

# Setup LazyVim starter config
RUN git clone --depth 1 https://github.com/LazyVim/starter /home/trustycage/.config/nvim \
    && rm -rf /home/trustycage/.config/nvim/.git

# Create project directory (volume mount point)
RUN mkdir -p /home/trustycage/project

WORKDIR /home/trustycage/project

# Keep container running
CMD ["sleep", "infinity"]
