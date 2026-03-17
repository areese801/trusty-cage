FROM ubuntu:24.04

ARG PYTHON_VERSION=3.12

# Avoid interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive

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

# Install Neovim v0.10.4 prebuilt (ARM64)
RUN curl -fsSL https://github.com/neovim/neovim/releases/download/v0.10.4/nvim-linux-arm64.tar.gz \
    | tar -xz -C /opt \
    && ln -s /opt/nvim-linux-arm64/bin/nvim /usr/local/bin/nvim

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user
RUN groupadd -g 1000 trustycage \
    && useradd -m -u 1000 -g trustycage -s /usr/bin/zsh trustycage \
    && echo "trustycage ALL=(root) NOPASSWD: /usr/sbin/iptables, /usr/sbin/ip6tables" >> /etc/sudoers.d/trustycage

USER trustycage
WORKDIR /home/trustycage

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
