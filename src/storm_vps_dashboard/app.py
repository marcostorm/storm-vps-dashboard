from __future__ import annotations

import time
from datetime import datetime

import streamlit as st

from storm_vps_dashboard.collector import Snapshot, collect, container_logs
from storm_vps_dashboard.config import load_config


def _status_badge(status: str, state: str) -> str:
    if state == "running":
        return f"🟢 {status}"
    if state in ("exited", "dead"):
        return f"🔴 {status}"
    if state in ("paused", "restarting"):
        return f"🟡 {status}"
    return f"⚪ {status}"


def _render(snapshot: Snapshot) -> None:
    disk_delta = f"{snapshot.disk.use_percent}% usado"
    mem_delta = f"{snapshot.memory.use_percent}% usado"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Load avg (1m / 5m / 15m)",
        f"{snapshot.uptime.load_1m:.2f}",
        f"5m: {snapshot.uptime.load_5m:.2f} · 15m: {snapshot.uptime.load_15m:.2f}",
        delta_color="off",
    )
    c2.metric(
        "Memória",
        f"{snapshot.memory.used_mb} / {snapshot.memory.total_mb} MB",
        mem_delta,
        delta_color="off",
    )
    c3.metric(
        "Disco /",
        f"{snapshot.disk.used} / {snapshot.disk.total}",
        disk_delta,
        delta_color="off",
    )
    running = sum(1 for c in snapshot.containers if c.state == "running")
    c4.metric("Containers (running / total)", f"{running} / {len(snapshot.containers)}")

    st.caption(snapshot.uptime.raw)

    st.subheader("Containers")
    if snapshot.containers:
        rows = [
            {
                "Nome": c.name,
                "Imagem": c.image,
                "Status": _status_badge(c.status, c.state),
                "Uptime": c.running_for,
                "Portas": c.ports,
            }
            for c in snapshot.containers
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("Nenhum container")

    st.subheader("Logs")
    if snapshot.containers:
        names = [c.name for c in snapshot.containers]
        col_sel, col_tail = st.columns([3, 1])
        selected = col_sel.selectbox("Container", names, key="log_container")
        tail = col_tail.number_input(
            "Linhas", min_value=10, max_value=500, value=50, step=10, key="log_tail"
        )
        if st.button("Puxar logs", key="log_fetch"):
            with st.spinner(f"Lendo últimas {tail} linhas de {selected}..."):
                try:
                    logs = container_logs(load_config(), selected, tail=int(tail))
                    st.code(logs or "(vazio)", language="log", height=400)
                except Exception as e:
                    st.error(f"Falha: {e}")
    else:
        st.info("Sem container pra ler logs")

    st.subheader("Docker system df")
    df = snapshot.docker_df
    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("Imagens", df.images_total_size, f"reclamável: {df.images_reclaimable}", delta_color="off")
    dc2.metric("Containers", df.containers_total_size)
    dc3.metric("Volumes", df.volumes_total_size)
    dc4.metric("Build cache", df.build_cache_total_size)


def run() -> None:
    import subprocess
    import sys
    from pathlib import Path

    app_path = Path(__file__).resolve()
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        "--server.port=8501",
        *sys.argv[1:],
    ]
    sys.exit(subprocess.call(cmd))


def main() -> None:
    st.set_page_config(
        page_title="Storm VPS Dashboard",
        page_icon="🌪️",
        layout="wide",
    )
    st.title("🌪️ Storm VPS Dashboard")

    cfg = load_config()
    with st.sidebar:
        st.markdown(f"**Host:** `{cfg.user}@{cfg.host}:{cfg.port}`")
        st.markdown(f"**Chave:** `{cfg.key_path}`")
        auto = st.toggle("Auto-refresh 30s", value=False)
        if st.button("Refresh agora", width="stretch"):
            st.rerun()

    start = time.perf_counter()
    try:
        snapshot = collect(cfg)
    except Exception as e:
        st.error(f"Falha ao coletar: {e}")
        st.stop()
    elapsed = time.perf_counter() - start

    st.caption(f"Coletado em {datetime.now().strftime('%H:%M:%S')} · {elapsed:.2f}s via SSH")
    _render(snapshot)

    if auto:
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
