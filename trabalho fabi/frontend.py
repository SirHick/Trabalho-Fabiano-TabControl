"""TabControl - Front-end Streamlit (estilo Espaço do Estudante SESI SENAI).
Rodar:  pip install streamlit pandas  ->  python -m streamlit run frontend.py
Mantenha na mesma pasta do tabcontrol.py (o backend NÃO é alterado)."""
import calendar
import html
import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import tabcontrol as tc

tc.criar_tabelas()
st.set_page_config("TabControl", "📟", layout="wide", initial_sidebar_state="collapsed")

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
CORES = ["#2e9e5b", "#2f7fc1", "#e0a030", "#d9534f", "#8e5bb5", "#17a2b8", "#e07b39", "#6c8f2f"]
esc = html.escape

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
html, body, .stApp, button, input, textarea {font-family:'Roboto',sans-serif !important}
#MainMenu, header, footer, [data-testid=stToolbar] {visibility:hidden}
.stApp {background:#f3f5f6}
.block-container {padding:0 2.5rem 3rem; max-width:1250px}
/* barra superior */
.st-key-topbar {background:@V@; margin:0 -2.5rem; padding:.8rem 2.5rem .5rem}
.st-key-topbar [data-testid=stHorizontalBlock] {align-items:center}
.logo {width:44px; height:44px; border-radius:50%; border:3px solid #fff; color:#fff; display:grid; place-items:center; font-weight:800; font-size:1.3rem}
.av {width:42px; height:42px; border-radius:50%; background:#fff; color:@VE@; display:grid; place-items:center; font-weight:700; border:2px solid #ffffff99; margin-left:auto}
.st-key-nav div[role=radiogroup] {justify-content:center; flex-wrap:nowrap; gap:.2rem; overflow-x:auto}
.st-key-nav label {padding:.5rem .9rem !important; border:0 !important; background:transparent !important; border-radius:24px !important; box-shadow:none !important}
.st-key-nav label:hover {background:#ffffff22 !important}
.st-key-nav label p {color:#fff !important; font-size:.8rem; font-weight:500; display:flex; flex-direction:column; align-items:center; gap:.2rem; white-space:nowrap; margin:0}
.st-key-nav label p span[data-testid=stIconMaterial] {font-size:1.45rem}
.st-key-nav label:has(input:checked) {background:#fff !important}
.st-key-nav label:has(input:checked) p {color:@VE@ !important}
/* hero (início) */
.st-key-hero {background:@V@; margin:-1rem -2.5rem 1.3rem; padding:1rem 2.5rem 2.2rem; border-radius:0 0 34px 34px; color:#fff}
.h1 {font-size:2.5rem; font-weight:500; line-height:1.1; margin:.6rem 0 1.1rem; color:#fff}
.who {display:flex; align-items:center; gap:.8rem; margin-bottom:1.1rem}
.who .av {margin:0} .acc {font-weight:500; margin:.4rem 0 .5rem}
.st-key-hero .stButton>button {background:#ffffff26; box-shadow:none; justify-content:flex-start; border-radius:12px}
.st-key-hero .stButton>button:hover {background:#ffffff40}
.st-key-hero h4 {color:#fff; font-weight:500; margin:.6rem 0 .8rem}
.aviso {display:flex; align-items:center; gap:.8rem; background:#ffffff26; color:#fff; border-radius:16px; padding:.85rem 1rem; margin-bottom:.7rem; font-size:.95rem}
.aviso .ic {flex:none; width:38px; height:38px; border-radius:50%; background:#f0649a; display:grid; place-items:center}
.aviso .tm {margin-left:auto; font-size:.75rem; white-space:nowrap}
.aviso.red {background:#d9534fcc} .aviso.amb {background:#e0a030cc}
/* cartões */
.card {background:#fff; border-radius:16px; padding:1.1rem 1.3rem; box-shadow:0 1px 6px #1b3a3510; margin-bottom:.9rem; border:1px solid #edf0f1}
.kpi {display:flex; align-items:center; gap:.9rem}
.kpi .ic {width:46px; height:46px; border-radius:14px; display:grid; place-items:center; font-size:1.3rem; background:#e3f3ef}
.kpi b {display:block; font-size:1.8rem; font-weight:700; color:#1d3b36; line-height:1} .kpi small {color:#6b7a78}
.sec {font-size:1.1rem; font-weight:500; color:#222; margin:.2rem 0 .7rem}
.pt {font-size:1.6rem; font-weight:500; color:#222; margin:.3rem 0 0; padding-top:.35rem}
.st-key-back button {border-radius:50%; width:42px; height:42px; padding:0; background:#fff; color:@V@; border:1px solid #e1e8e6; box-shadow:0 1px 4px #0001}
/* lista (estilo Desempenho) */
.li .lt {display:flex; justify-content:space-between; align-items:flex-start; font-size:1.05rem; margin-bottom:.5rem}
.li .ln {display:flex; align-items:center; gap:.6rem; color:#667; font-size:.85rem; margin:.4rem 0}
.ci {width:26px; height:26px; border-radius:50%; background:#e8f1ef; display:grid; place-items:center; font-size:.75rem; flex:none}
.lf {border-top:1px solid #eceff0; margin-top:.7rem; padding-top:.6rem; font-size:.8rem; color:#555}
.badge {display:inline-block; padding:.12rem .7rem; border-radius:6px; font-size:.72rem; font-weight:500; color:#fff; white-space:nowrap}
.b-disponivel,.b-ok,.b-concluida,.b-resolvido {background:#2e9e5b} .b-emprestado,.b-ativa {background:#2f7fc1}
.b-manutencao,.b-defeito,.b-cancelada {background:#d9534f} .b-observacao {background:#8a94a0} .b-aberto {background:#e0a030}
.bar {background:#e6ecec; border-radius:99px; height:9px; overflow:hidden; margin:.7rem 0 .5rem} .bar div {height:100%; border-radius:99px}
.tab {border-top:4px solid var(--c)}
.mini {display:flex; gap:.7rem; flex-wrap:wrap}
.mini div {flex:1; min-width:140px; border:1px solid #e6ecec; border-radius:14px; padding:.7rem .9rem}
.mini b {display:block; font-size:1.5rem; color:#1d3b36; margin-top:.3rem} .mini small {color:#889}
.dt {flex:none; width:44px; height:52px; border-radius:10px; background:#fde4ee; color:#f0649a; display:grid; place-items:center; text-align:center; line-height:1.05}
.dt b {font-size:1.3rem; font-weight:500} .dt small {font-size:.7rem}
.nw {display:flex; gap:.9rem; align-items:center; border:1px solid #edf0f1; border-radius:14px; padding:.7rem; margin-bottom:.6rem; font-size:.88rem}
/* calendário */
.cal {background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 6px #1b3a3512}
.cal table {width:100%; border-collapse:collapse; table-layout:fixed}
.cal th {background:@V@; color:#fff; padding:.75rem; font-weight:600}
.cal td {border:1px solid #e9eeed; vertical-align:top; height:115px; padding:.3rem .45rem; font-size:.72rem; color:#333}
.cal.wk td {height:360px} .cal td.out {background:#fafbfb; color:#aaa}
.dn {text-align:center; font-size:.8rem; color:#444; margin-bottom:.25rem}
.today {display:inline-block; background:@V@; color:#fff; width:22px; height:22px; line-height:22px; border-radius:50%}
.ev {white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin:.12rem 0} .ev i {display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:.3rem}
.more {color:#667; font-size:.7rem}
.mc {width:100%; border-collapse:collapse; font-size:.72rem; text-align:center} .mc td, .mc th {padding:.28rem 0; color:#555; font-weight:400}
.mc .hv {font-weight:700; color:@VE@; text-decoration:underline}
.mw {display:flex; gap:1.2rem; flex-wrap:wrap} .mw>div:first-child {width:250px}
.ml {flex:1; min-width:240px} .evc {border:1px solid #e6ecec; border-left:4px solid @V@; border-radius:6px; padding:.35rem .6rem; margin-bottom:.45rem; font-size:.78rem}
/* chips, abas, botões, campos */
div[role=radiogroup] {gap:.45rem; flex-wrap:wrap}
div[role=radiogroup] label {border-radius:99px; padding:.35rem 1.05rem; cursor:pointer; margin:0; background:#fff; border:1px solid #cfe3de; transition:.15s}
div[role=radiogroup] label p {color:@VE@}
div[role=radiogroup] label:has(input:checked) {background:#dff1ec; border-color:#dff1ec}
div[role=radiogroup] label:has(input:checked) p {font-weight:700}
div[role=radiogroup] label[data-baseweb=radio] > div:first-child, div[role=radiogroup] label > span:first-child {display:none}
.stTabs [data-baseweb=tab-list] {gap:.5rem; border:0}
.stTabs [data-baseweb=tab] {border-radius:99px; padding:.4rem 1.2rem; height:auto; background:#fff; border:1px solid #cfe3de; color:@VE@}
.stTabs [aria-selected=true] {background:#dff1ec; border-color:#dff1ec; font-weight:700}
.stTabs [data-baseweb=tab-highlight], .stTabs [data-baseweb=tab-border] {display:none}
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button {border-radius:99px; border:0; background:@V@; color:#fff; font-weight:500; padding:.45rem 1.4rem; transition:.15s}
.stButton>button:hover, .stFormSubmitButton>button:hover, .stDownloadButton>button:hover {background:@VE@; color:#fff}
.stDownloadButton>button {background:#fff; color:@VE@; border:1px solid #cfe3de}
.stDownloadButton>button:hover {background:#eef7f5; color:@VE@}
[data-baseweb=select]>div, .stTextInput input, .stTextArea textarea, .stDateInput input, .stTimeInput input {border-radius:12px !important; background:#fff !important}
[data-testid=stForm] {background:#fff; border:1px solid #edf0f1; border-radius:16px; padding:1.3rem}
[data-testid=stDataFrame] {border-radius:12px; overflow:hidden} [data-testid=stAlert] {border-radius:14px}
h3 {font-weight:500; color:#222}
</style>""".replace("@VE@", "#2c7f70").replace("@V@", "#3d9d8c")
st.markdown(CSS, unsafe_allow_html=True)

P = {"ini": ":material/home: Início", "tab": ":material/tablet_mac: Tablets", "mov": ":material/swap_horiz: Retirar/Devolver",
     "res": ":material/event_available: Reservas", "qua": ":material/calendar_month: Horários", "pro": ":material/school: Professores",
     "his": ":material/history: Histórico", "obs": ":material/chat: Observações"}
ss = st.session_state


def ir(k):
    ss.nav = P[k]


# ---------- utilidades ----------
def q(sql, p=()):
    with tc.conectar() as con:
        return [dict(r) for r in con.execute(sql, p).fetchall()]


def badge(t):
    return f'<span class="badge b-{t}">{t.replace("manutencao", "manutenção").upper()}</span>'


def flash(res):
    ss.flash = (res[0], res[1])
    st.rerun()


tela = tc.para_tela


def tablets():
    return q("""SELECT t.*, (SELECT p.nome FROM emprestimos e JOIN professores p ON p.id=e.professor_id
                WHERE e.tablet_id=t.id AND e.devolucao IS NULL) AS com FROM tablets t ORDER BY t.codigo""")


def profs():
    return q("SELECT * FROM professores ORDER BY nome")


def pick_prof(label="Professor", key=None, opcional=False):
    op = {f"{p['nome']} ({p['tag_rfid']})": p for p in profs()}
    sel = st.selectbox(label, ([""] if opcional else []) + list(op), key=key)
    return op.get(sel)


def pick_tablet(label="Tablet", filtro=None, key=None):
    op = {f"{t['codigo']} · {t['bateria']}% · {t['status']}": t for t in tablets() if not filtro or filtro(t)}
    return op.get(st.selectbox(label, list(op), key=key))


def confirmar_exclusao():
    c = ss.get("conf")
    if not c:
        return
    tipo, id_, msg = c
    st.warning(msg)
    a, b, _ = st.columns([1.3, 1, 4])
    if a.button("Excluir mesmo assim", key="c_ok"):
        ss.conf = None
        flash((tc.excluir_professor if tipo == "prof" else tc.excluir_tablet)(id_, True))
    if b.button("Cancelar", key="c_no"):
        ss.conf = None
        st.rerun()


def excluir(tipo, id_):
    r = (tc.excluir_professor if tipo == "prof" else tc.excluir_tablet)(id_)
    if len(r) > 2 and r[2]:
        ss.conf = (tipo, id_, r[1])
        st.rerun()
    flash(r)


def tabela(rows, cols):
    if not rows:
        st.info("Nenhum registro ainda.")
        return
    st.dataframe(pd.DataFrame(rows)[list(cols)].rename(columns=cols), hide_index=True, use_container_width=True)


def titulo(t):
    a, b = st.columns([.6, 9])
    a.button(":material/arrow_back:", key="back", on_click=ir, args=("ini",))
    b.markdown(f'<div class="pt">{t}</div>', unsafe_allow_html=True)
    st.write("")


def li(tit, bd, linhas, foot=""):
    ls = "".join(f'<div class="ln"><span class="ci">{i}</span>{t}</div>' for i, t in linhas)
    return (f'<div class="card li"><div class="lt"><b>{tit}</b><span>{bd}</span></div>{ls}'
            + (f'<div class="lf">{foot}</div>' if foot else "") + "</div>")


# ---------- quadro de horários ----------
def eventos(filtro=None):
    rs = q("""SELECT r.id, r.inicio, r.fim, r.status, p.nome, t.codigo, t.id tid FROM reservas r
              JOIN professores p ON p.id=r.professor_id JOIN tablets t ON t.id=r.tablet_id
              WHERE r.status!='cancelada' ORDER BY r.inicio""")
    ev = {}
    for r in rs:
        if not filtro or r["codigo"] == filtro:
            ev.setdefault(r["inicio"][:10], []).append(r)
    return ev


def grade(semanas, ev, mes, lim, cls=""):
    hoje = date.today()
    h = f'<div class="cal {cls}"><table><tr>' + "".join(f"<th>{d}</th>" for d in ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]) + "</tr>"
    for sem in semanas:
        h += "<tr>"
        for d in sem:
            es = ev.get(d.isoformat(), [])
            num = f'<span class="today">{d.day}</span>' if d == hoje else str(d.day)
            li_ = "".join(
                f'<div class="ev" style="{"opacity:.55" if e["status"] == "concluida" else ""}" '
                f'title="{esc(e["codigo"])} · {esc(e["nome"])} · {tela(e["inicio"])} → {tela(e["fim"])[-5:]}">'
                f'<i style="background:{CORES[e["tid"] % len(CORES)]}"></i><b>{e["inicio"][11:]}</b> {esc(e["codigo"])} {esc(e["nome"].split()[0])}</div>'
                for e in es[:lim])
            if len(es) > lim:
                li_ += f'<div class="more">+ {len(es) - lim} eventos</div>'
            out = "out" if mes and d.month != mes else ""
            h += f'<td class="{out}"><div class="dn">{num}</div>{li_}</td>'
        h += "</tr>"
    return h + "</table></div>"


def pg_quadro():
    titulo("Quadro de horários")
    ss.setdefault("ref", date.today())
    ss.setdefault("modo", "Mensal")

    def mover(s):
        r = ss.ref
        if ss.modo == "Mensal":
            m = r.month - 1 + s
            ss.ref = date(r.year + m // 12, m % 12 + 1, 1)
        else:
            ss.ref = r + timedelta(days=7 * s)

    r, mensal = ss.ref, ss.modo == "Mensal"
    ini_sem = r - timedelta(days=(r.weekday() + 1) % 7)
    rotulo = f"{MESES[r.month - 1]} {r.year}" if mensal else f"{ini_sem:%d/%m} – {ini_sem + timedelta(days=6):%d/%m/%Y}"
    c = st.columns([.5, 1.8, .5, 1.2, 1.7, 1.5, 1.6], vertical_alignment="center")
    c[0].button(":material/chevron_left:", key="prev", on_click=mover, args=(-1,))
    c[1].markdown(f'<div class="card" style="margin:0;padding:.5rem 1rem;text-align:center;color:#2c7f70;font-weight:500">🗓️ {rotulo}</div>',
                  unsafe_allow_html=True)
    c[2].button(":material/chevron_right:", key="next", on_click=mover, args=(1,))
    c[3].selectbox("Visão", ["Mensal", "Semanal"], key="modo", label_visibility="collapsed")
    filtro = c[4].selectbox("Tablet", ["Todos os tablets"] + [t["codigo"] for t in tablets()], label_visibility="collapsed")
    ev = eventos(None if filtro.startswith("Todos") else filtro)
    todas = [dict(Tablet=e["codigo"], Professor=e["nome"], Início=tela(e["inicio"]), Fim=tela(e["fim"]), Status=e["status"])
             for v in ev.values() for e in v]
    c[5].download_button(":material/download: Baixar quadro", pd.DataFrame(todas).to_csv(index=False).encode("utf-8-sig"),
                         "quadro_reservas.csv", "text/csv", disabled=not todas)
    c[6].button(":material/add: Nova reserva", key="nr", on_click=ir, args=("res",))
    st.write("")
    if mensal:
        st.markdown(grade(calendar.Calendar(6).monthdatescalendar(r.year, r.month), ev, r.month, 3), unsafe_allow_html=True)
    else:
        st.markdown(grade([[ini_sem + timedelta(days=i) for i in range(7)]], ev, None, 50, "wk"), unsafe_allow_html=True)
    leg = "".join(f'<span style="margin-right:1rem"><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{CORES[t["id"] % len(CORES)]}"></i> {esc(t["codigo"])}</span>'
                  for t in tablets())
    st.markdown(f'<p style="margin-top:.8rem;font-size:.85rem;color:#556">{leg}</p>', unsafe_allow_html=True)


# ---------- páginas ----------
def mini_cal(ev):
    hj = date.today()
    h = '<table class="mc"><tr>' + "".join(f"<th>{d}</th>" for d in "DSTQQSS") + "</tr>"
    for sem in calendar.Calendar(6).monthdatescalendar(hj.year, hj.month):
        h += "<tr>" + "".join(
            f'<td class="{"hv" if d.isoformat() in ev else ""}">' + (f'<span class="today">{d.day}</span>' if d == hj else (str(d.day) if d.month == hj.month else ""))
            + "</td>" for d in sem) + "</tr>"
    return h + "</table>"


def pg_inicio():
    ts = tablets()
    cont = lambda s: sum(t["status"] == s for t in ts)
    baixa = [t for t in ts if t["bateria"] < tc.BATERIA_MINIMA]
    av = [("red", "🔋", f"{t['codigo']} com bateria em {t['bateria']}%") for t in baixa]
    av += [("red", "🛠️", f"{t['codigo']} em manutenção") for t in ts if t["status"] == "manutencao"]
    n_def = q("SELECT COUNT(*) n FROM observacoes WHERE tipo='defeito' AND resolvido=0")[0]["n"]
    if n_def:
        av.append(("amb", "⚠️", f"{n_def} defeito(s) em aberto"))
    av += [("", "📟", f"{t['codigo']} está com {esc(t['com'])}") for t in ts if t["status"] == "emprestado"]

    with st.container(key="hero"):
        a, b = st.columns([3, 2], gap="large")
        with a:
            st.markdown('<div class="h1">Bem-vindo(a) ao<br>TabControl</div><div class="who"><div class="av">AD</div>'
                        '<div><b style="font-size:1.3rem;font-weight:500">Administração</b><br><small>Armário de tablets · Centro WEG</small></div></div>'
                        '<div class="acc">Acessar</div>', unsafe_allow_html=True)
            for col, (ic, l, p) in zip(st.columns(3), [("upload", "Retirar tablet", "mov"), ("download", "Devolver tablet", "mov"),
                                                        ("event_available", "Nova reserva", "res")]):
                col.button(f":material/{ic}: {l}", key=f"q_{l}", on_click=ir, args=(p,), use_container_width=True)
        with b:
            st.markdown("#### Últimos avisos")
            for cls, ic, tx in (av or [("", "✅", "Tudo certo com o armário")])[:4]:
                st.markdown(f'<div class="aviso {cls}"><div class="ic">{ic}</div><div>{tx}</div><div class="tm">agora</div></div>', unsafe_allow_html=True)

    for col, (n, l, ic) in zip(st.columns(4), [(len(ts), "Total de tablets", "📟"), (cont("disponivel"), "Disponíveis", "✅"),
                                               (cont("emprestado"), "Emprestados", "👤"), (len(baixa), f"Bateria < {tc.BATERIA_MINIMA}%", "🔋")]):
        col.markdown(f'<div class="card kpi"><div class="ic">{ic}</div><div><b>{n}</b><small>{l}</small></div></div>', unsafe_allow_html=True)

    esq, dir_ = st.columns([2, 1], gap="large")
    with esq:
        ev, hj = eventos(), date.today()
        hoje_ev = ev.get(hj.isoformat(), [])
        itens = "".join(f'<div class="evc"><b>{esc(e["codigo"])}</b> · {esc(e["nome"])}<br><small style="color:#778">{e["inicio"][11:]} → {e["fim"][11:]}</small></div>'
                        for e in hoje_ev[:4]) or '<small style="color:#889">Sem reservas hoje.</small>'
        st.markdown(f'<div class="card"><div class="sec">{MESES[hj.month - 1]}</div><div class="mw"><div>{mini_cal(ev)}</div>'
                    f'<div class="ml">{itens}</div></div><div style="text-align:right;font-size:.75rem;color:#889">{len(hoje_ev)} eventos hoje</div></div>',
                    unsafe_allow_html=True)
        cards = "".join(f'<div>{badge(t["status"])}<br><span style="font-size:.85rem">{esc(t["codigo"])}</span><b>{t["bateria"]}%</b><small>Bateria</small></div>' for t in ts)
        st.markdown(f'<div class="card"><div class="sec">Tablets</div><div class="mini">{cards or "<small>Nenhum tablet cadastrado.</small>"}</div></div>',
                    unsafe_allow_html=True)
        if not ts and st.button("Carregar dados de exemplo"):
            tc.carregar_exemplo()
            flash((True, "Dados de exemplo carregados."))
    with dir_:
        st.markdown('<div class="sec">Ocorrências recentes</div>', unsafe_allow_html=True)
        obs = q("""SELECT o.data, o.tipo, o.texto, t.codigo FROM observacoes o JOIN tablets t ON t.id=o.tablet_id ORDER BY o.data DESC LIMIT 4""")
        for o in obs:
            st.markdown(f'<div class="nw"><div class="dt"><small>{MESES[int(o["data"][5:7]) - 1][:3]}</small><b>{int(o["data"][8:10])}</b></div>'
                        f'<div><b>{esc(o["codigo"])}</b> {badge(o["tipo"])}<br><small>{esc(o["texto"][:70])}</small></div></div>', unsafe_allow_html=True)
        if not obs:
            st.info("Nenhuma ocorrência registrada.")


def pg_tablets():
    titulo("Tablets")
    t1, t2, t3, t4 = st.tabs(["Frota", "Cadastrar", "Atualizar bateria/hardware", "Excluir"])
    with t1:
        f = st.radio("Filtro", ["todos", "disponivel", "emprestado", "manutencao"], horizontal=True, label_visibility="collapsed")
        ts = [t for t in tablets() if f == "todos" or t["status"] == f]
        if not ts:
            st.info("Nenhum tablet encontrado.")
        cols = st.columns(3)
        for i, t in enumerate(ts):
            cor = "#2e9e5b" if t["bateria"] >= 50 else "#e0a030" if t["bateria"] >= tc.BATERIA_MINIMA else "#d9534f"
            cc = {"disponivel": "#2e9e5b", "emprestado": "#2f7fc1", "manutencao": "#d9534f"}[t["status"]]
            extra = f"<br>👤 {esc(t['com'])}" if t["com"] else ""
            cols[i % 3].markdown(f"""<div class="card tab" style="--c:{cc}"><b style="font-size:1.15rem">{esc(t['codigo'])}</b> &nbsp;{badge(t['status'])}
              <div class="bar"><div style="width:{t['bateria']}%;background:{cor}"></div></div>
              🔋 {t['bateria']}% &nbsp; ⚙️ hardware {badge(t['hardware'])}<br><small>Tag: {esc(t['tag_rfid'])}</small>{extra}</div>""",
                                 unsafe_allow_html=True)
    with t2, st.form("f_tab", clear_on_submit=True):
        c, tag = st.text_input("Código do tablet (ex: TAB-04)"), st.text_input("Tag RFID do tablet")
        if st.form_submit_button("Cadastrar tablet"):
            flash(tc.cadastrar_tablet(c.strip(), tag.strip()) if c.strip() and tag.strip() else (False, "Preencha todos os campos."))
    with t3:
        t = pick_tablet(key="up_t")
        if t:
            with st.form("f_up"):
                b = st.slider("Bateria (%)", 0, 100, t["bateria"])
                h = st.radio("Hardware", ["ok", "defeito"], index=int(t["hardware"] != "ok"), horizontal=True)
                if st.form_submit_button("Atualizar"):
                    flash(tc.atualizar_status_tablet(t["codigo"], b, h))
    with t4:
        confirmar_exclusao()
        t = pick_tablet(key="del_t")
        if t and st.button("Excluir tablet"):
            excluir("tab", t["id"])


def pg_movimentar():
    titulo("Retirar / Devolver")
    a, b = st.tabs(["Retirar tablet", "Devolver tablet"])
    with a:
        c1, c2 = st.columns(2)
        with c1:
            p = pick_prof(key="ret_p")
        with c2:
            t = pick_tablet(filtro=lambda x: x["status"] == "disponivel", key="ret_t")
        st.caption("No armário real, a identificação é feita aproximando as tags RFID do leitor.")
        if p and t and st.button("Liberar retirada"):
            flash(tc.retirar(p["tag_rfid"], t["tag_rfid"]))
        elif not t:
            st.info("Nenhum tablet disponível para retirada.")
    with b:
        t = pick_tablet(filtro=lambda x: x["status"] == "emprestado", key="dev_t")
        if t:
            st.write(f"Com: **{t['com']}**")
            bat = st.slider("Bateria atual (%)", 0, 100, t["bateria"], key="dev_b")
            hw = st.radio("Hardware está ok?", ["ok", "defeito"], horizontal=True, key="dev_h")
            if st.button("Registrar devolução"):
                flash(tc.devolver(t["tag_rfid"], bat, hw))
        else:
            st.info("Nenhum tablet emprestado no momento.")


def pg_reservas():
    titulo("Reservas")
    a, b = st.tabs(["Nova reserva", "Minhas reservas"])
    with a:
        c1, c2 = st.columns(2)
        with c1:
            p = pick_prof(key="rs_p")
        with c2:
            t = pick_tablet(filtro=lambda x: x["status"] != "manutencao", key="rs_t")
        d, h1, h2 = st.columns(3)
        dia = d.date_input("Dia", date.today(), min_value=date.today(), format="DD/MM/YYYY")
        ini, fim = h1.time_input("Início", time(8, 0)), h2.time_input("Fim", time(10, 0))
        st.caption(f"Reservas com até {tc.DIAS_MAX_ANTECEDENCIA} dias de antecedência. Veja o quadro completo em Horários.")
        if p and t and st.button("Confirmar reserva"):
            flash(tc.reservar(p["tag_rfid"], t["codigo"], datetime.combine(dia, ini), datetime.combine(dia, fim)))
    with b:
        f = st.radio("Status", ["todas", "ativa", "concluida", "cancelada"], horizontal=True, label_visibility="collapsed")
        rs = q("""SELECT r.id, r.inicio, r.fim, r.status, p.nome, p.tag_rfid tag, t.codigo FROM reservas r
                  JOIN professores p ON p.id=r.professor_id JOIN tablets t ON t.id=r.tablet_id ORDER BY r.inicio DESC""")
        rs = [r for r in rs if f == "todas" or r["status"] == f]
        if not rs:
            st.info("Nenhuma reserva encontrada.")
        for r in rs:
            c1, c2 = st.columns([6, 1], vertical_alignment="center")
            c1.markdown(li(esc(r["codigo"]), badge(r["status"]), [("👤", esc(r["nome"])), ("🕒", f"{tela(r['inicio'])} → {tela(r['fim'])[-5:]}")],
                           f"Reserva #{r['id']}"), unsafe_allow_html=True)
            if r["status"] == "ativa" and c2.button("Cancelar", key=f"cr{r['id']}"):
                flash(tc.cancelar_reserva(r["id"], r["tag"]))


def pg_professores():
    titulo("Professores")
    a, b, c = st.tabs(["Lista", "Cadastrar", "Excluir"])
    with a:
        tabela(profs(), {"nome": "Nome", "email": "E-mail", "tag_rfid": "Tag RFID"})
    with b, st.form("f_prof", clear_on_submit=True):
        n, e, tag = st.text_input("Nome"), st.text_input("E-mail"), st.text_input("Tag RFID")
        if st.form_submit_button("Cadastrar professor"):
            flash(tc.cadastrar_professor(n.strip(), e.strip(), tag.strip()) if n.strip() and e.strip() and tag.strip()
                  else (False, "Preencha todos os campos."))
    with c:
        confirmar_exclusao()
        p = pick_prof(key="del_p")
        if p and st.button("Excluir professor"):
            excluir("prof", p["id"])


def pg_historico():
    titulo("Histórico")
    h = q("""SELECT p.nome, t.codigo, e.retirada, e.devolucao, e.bateria_retirada br, e.bateria_devolucao bd
             FROM emprestimos e JOIN professores p ON p.id=e.professor_id JOIN tablets t ON t.id=e.tablet_id
             ORDER BY e.retirada DESC, e.id DESC""")
    if not h:
        st.info("Nenhum empréstimo registrado.")
        return
    df = pd.DataFrame(h)
    c1, c2 = st.columns(2)
    fp, ft = c1.multiselect("Professor", sorted(df.nome.unique())), c2.multiselect("Tablet", sorted(df.codigo.unique()))
    if fp:
        df = df[df.nome.isin(fp)]
    if ft:
        df = df[df.codigo.isin(ft)]
    df["retirada"], df["devolucao"] = df.retirada.map(tela), df.devolucao.map(lambda x: "Em uso" if pd.isna(x) or not x else tela(x))
    df["bateria"] = df.br.astype(str) + "% → " + df.bd.map(lambda x: "-" if pd.isna(x) else f"{int(x)}%")
    df = df[["nome", "codigo", "retirada", "devolucao", "bateria"]]
    df.columns = ["Professor", "Tablet", "Retirada", "Devolução", "Bateria (ret → dev)"]
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button(":material/download: Baixar CSV", df.to_csv(index=False).encode("utf-8-sig"), "historico_tabcontrol.csv", "text/csv")


def pg_observacoes():
    titulo("Observações")
    a, b = st.tabs(["Registrar", "Ocorrências"])
    with a:
        t = pick_tablet(key="ob_t")
        p = pick_prof("Professor (opcional)", key="ob_p", opcional=True)
        txt = st.text_area("O que aconteceu?")
        df = st.checkbox("É um defeito que impede o uso (bloqueia o tablet e envia para manutenção)")
        if t and st.button("Registrar"):
            flash(tc.registrar_observacao(t["codigo"], p["tag_rfid"] if p else "", txt, df))
    with b:
        obs = q("""SELECT o.data, o.tipo, o.resolvido, o.texto, t.codigo, COALESCE(p.nome,'Anônimo') nome FROM observacoes o
                   JOIN tablets t ON t.id=o.tablet_id LEFT JOIN professores p ON p.id=o.professor_id ORDER BY o.data DESC""")
        if not obs:
            st.info("Nenhuma ocorrência registrada.")
        for o in obs:
            est = badge("resolvido") if o["resolvido"] else badge("aberto") if o["tipo"] == "defeito" else ""
            st.markdown(li(esc(o["codigo"]), badge(o["tipo"]) + " " + est,
                           [("👤", esc(o["nome"])), ("🗓️", tela(o["data"])), ("💬", esc(o["texto"]))]), unsafe_allow_html=True)


# ---------- layout ----------
PAGINAS = {P["ini"]: pg_inicio, P["tab"]: pg_tablets, P["mov"]: pg_movimentar, P["res"]: pg_reservas,
           P["qua"]: pg_quadro, P["pro"]: pg_professores, P["his"]: pg_historico, P["obs"]: pg_observacoes}
ss.setdefault("nav", P["ini"])
with st.container(key="topbar"):
    c1, c2, c3 = st.columns([.6, 9, .6])
    c1.markdown('<div class="logo">T</div>', unsafe_allow_html=True)
    with c2, st.container(key="menu"):
        st.radio("Menu", list(PAGINAS), horizontal=True, label_visibility="collapsed", key="nav")
    c3.markdown('<div class="av">AD</div>', unsafe_allow_html=True)
if "flash" in ss:
    ok, msg = ss.pop("flash")
    (st.success if ok else st.error)(msg)
st.write("")
PAGINAS[ss.nav]()