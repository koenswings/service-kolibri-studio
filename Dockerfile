FROM python:3.10-slim-bookworm

# Set the timezone
RUN ln -fs /usr/share/zoneinfo/America/Los_Angeles /etc/localtime

# Studio source directory ######################################################
RUN mkdir /src
WORKDIR /src
################################################################################


# System packages ##############################################################
ENV DEBIAN_FRONTEND noninteractive
# Default Python file.open file encoding to UTF-8 instead of ASCII, workaround for le-utils setup.py issue
ENV LANG C.UTF-8
RUN apt-get update && \
    apt-get -y install \
        curl fish man \
        python3-pip python3-dev \
        gcc libpq-dev libssl-dev libffi-dev make git gettext libjpeg-dev ffmpeg

# Pin, Download and install node 16.x
RUN apt-get update \
    && apt-get install -y ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_16.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && echo "Package: nodejs" >> /etc/apt/preferences.d/preferences \
    && echo "Pin: origin deb.nodesource.com" >> /etc/apt/preferences.d/preferences \
    && echo "Pin-Priority: 1001" >> /etc/apt/preferences.d/preferences\
    && apt-get update \
    && apt-get install -y nodejs
################################################################################


# Node packages ################################################################
RUN npm install -g yarn && npm cache clean --force
#COPY ./package.json ./yarn.lock   /src/
COPY . /src/
#COPY .* /src/
#KSW Run yarn install twice to make sure everything got installed
RUN yarn install 
RUN yarn install && yarn cache clean
################################################################################


# Python packages ##############################################################
COPY requirements.txt requirements-dev.txt   /src/
RUN pip install --no-cache-dir --upgrade pip

# install pinned deps from pip-tools into system
RUN pip install -r requirements.txt
RUN pip install -r requirements-dev.txt
################################################################################

# KSW - Build ##################################################################
# We get a webpack exit code of 137 indicating a memory issue - both on Mac 
# as well as the Pi5
# RUN yarn run build
################################################################################


# Final cleanup ################################################################
RUN apt-get -y autoremove
################################################################################

CMD ["yarn", "run", "devserver"]
