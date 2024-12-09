FROM python:3.11-slim
RUN apt-get update && apt-get install --no-install-recommends -qq git iputils-ping curl build-essential
RUN curl https://sh.rustup.rs -sSf | bash -s -- -y --profile=minimal
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --upgrade \
	asyncclick==8.1.3.4 \
	anyio==3.6.2 \
	uvloop==0.17.0 \
	wakeonlan==3.0.0 \
	icmplib==3.0.4 \
	requests==2.30.0 \
	pymodbus==3.5.4 \
	aiohttp==3.8.5 \
	aiomqtt==1.1.0 \
	pyyaml==6.0.1 \
	aiosnmp==0.7.2 \
	git+https://github.com/worosom/aiopjlink
RUN pip install --no-cache-dir PyWebOSTV wsaccel
RUN echo "{}" > /opt/weboscreds.json
WORKDIR /app
