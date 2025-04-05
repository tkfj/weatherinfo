# Dockerfile
FROM python:3.13-slim-bullseye

# システムアップデート & 日本語ロケール用パッケージインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        sudo \
        locales \
        build-essential \
        fonts-ipafont-gothic \
        git ca-certificates gnupg \
        && rm -rf /var/lib/apt/lists/*

# ロケールの設定: ja_JP.UTF-8 を有効化
RUN sed -i -E 's/# (ja_JP.UTF-8)/\1/' /etc/locale.gen \
    && locale-gen

ENV LANG ja_JP.UTF-8
ENV LANGUAGE ja_JP:ja
ENV LC_ALL ja_JP.UTF-8
ENV TZ Asia/Tokyo
ENV DEBIAN_FRONTEND=noninteractive


# Pythonパッケージインストール
RUN pip install --no-cache-dir \
    slack-sdk \
    python-dotenv \
    Pillow \
    requests 


# 作業ディレクトリを設定
WORKDIR /usr/src/app

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

RUN groupadd --gid ${USER_GID} ${USERNAME} \
  && useradd -m --shell /bin/bash --uid ${USER_UID} --gid ${USER_GID} ${USERNAME} \
  && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

RUN echo "alias ll='ls -alF'" >> /etc/bash.bashrc && \
    echo "alias la='ls -A'" >> /etc/bash.bashrc && \
    echo "alias l='ls -CF'" >> /etc/bash.bashrc

# 必要に応じてソースをコピー (docker-compose で volume マウントする場合は必須ではない)
# COPY ./src/ /usr/src/app/
# COPY ./.env /usr/src/app/