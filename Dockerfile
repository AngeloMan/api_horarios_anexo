# ---------------------------------------------------------------------------
# Dockerfile de teste: compila apenas o fet-cl (sem GUI) e roda contra um .fet
#
# IMPORTANTE — validado nesta análise:
#   O mirror "rodolforg/fet" (branches dev/upstream) está desatualizado
#   (parou em 5.37.5, de 2019) e QUEBRA ao processar arquivos .fet gerados
#   pelo FET 7.x (assertion failure em ConstraintTeacherMaxDaysPerWeek).
#
#   Este Dockerfile usa o mirror "bhavyasaggi/fet", que reflete a versão
#   7.8.5 (abril/2026) e foi testado com sucesso contra um arquivo .fet
#   real gerado no FET 7.9.1. Antes de ir para produção, prefira baixar o
#   tarball oficial em https://lalescu.ro/liviu/fet/download.html — o
#   mirror do GitHub pode ficar desatualizado novamente no futuro.
# ---------------------------------------------------------------------------

# ---- Stage 1: build ---------------------------------------------------
FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential qtbase5-dev qt5-qmake \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
# Fixe o commit/tag em produção (evita builds não reprodutíveis):
#
# Se o clone ainda falhar por certificado MESMO com ca-certificates instalado,
# a causa provavelmente é um proxy corporativo/antivírus com inspeção SSL na
# sua máquina Windows (comum com Kaspersky, ESET, Zscaler, VPN corporativa
# etc.), interceptando o tráfego do Docker Desktop com um certificado próprio.
# Nesse caso, o Docker Desktop precisa confiar no certificado raiz da sua
# empresa -- veja Settings > Resources > Proxies no Docker Desktop, ou peça
# o certificado .crt da sua TI e adicione-o à imagem antes deste RUN.
RUN git clone --depth 1 https://github.com/bhavyasaggi/fet.git .

# Compila SOMENTE o fet-cl (QT -= gui no próprio .pro) — sem QtWidgets/QtGui
WORKDIR /src/src
RUN qmake src-cl.pro && make -j"$(nproc)" && strip ../fet-cl

# ---- Stage 2: runtime ---------------------------------------------------
FROM ubuntu:24.04 AS runtime

# python3 é só para poder rodar test_fet_pipeline.py DENTRO do container
# (smoke test). Se você só quer o fet-cl para uso em produção via API,
# pode remover "python3" daqui e deixar a imagem ainda mais enxuta --
# o smoke test roda igual fora do container, apontando --fet-cl para o
# binário extraído (ex.: via "docker cp").
RUN apt-get update && apt-get install -y --no-install-recommends \
    libqt5core5t64 python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/fet-cl /usr/local/bin/fet-cl

RUN useradd -m fetrunner
USER fetrunner
WORKDIR /home/fetrunner

ENTRYPOINT ["fet-cl"]
CMD ["--version"]