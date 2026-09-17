FROM python:3.12.14-slim

# libgomp1: LightGBM が使う OpenMP ランタイム
# fonts-noto-cjk: matplotlib のグラフに日本語ラベルを表示するためのフォント
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt

# 図の日本語が豆腐（□）にならないよう、matplotlib の既定フォントを指定する
ENV MPLCONFIGDIR=/tmp/matplotlib
RUN mkdir -p /tmp/matplotlib && python - <<'PY'
import matplotlib, pathlib
cfg = pathlib.Path(matplotlib.get_configdir())
cfg.mkdir(parents=True, exist_ok=True)
(cfg / "matplotlibrc").write_text(
    "font.family: Noto Sans CJK JP\n"
    "axes.unicode_minus: False\n",
    encoding="utf-8",
)
print("matplotlibrc:", cfg / "matplotlibrc")
PY

CMD ["sleep", "infinity"]
