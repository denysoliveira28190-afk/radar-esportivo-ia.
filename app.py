import os, math, sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
import streamlit as st

st.set_page_config(page_title='Radar Esportivo IA', page_icon='⚽', layout='wide')
DB='radar.db'
COMPETITIONS={'Brasileirão Série A':'BSA','Premier League':'PL','La Liga':'PD','Bundesliga':'BL1','Serie A (Itália)':'SA','Ligue 1':'FL1','Champions League':'CL','Libertadores':'CLI'}

def init_db():
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS analises (id INTEGER PRIMARY KEY, criado TEXT, jogo TEXT, origem TEXT, casa REAL, empate REAL, fora REAL, over25 REAL, observacao TEXT)')

def poisson(k, lam):
    return math.exp(-lam)*lam**k/math.factorial(k)

def estimate(home_for,home_against,away_for,away_against):
    # Heurística demonstrativa: médias informadas manualmente; não calibrada para apostas.
    lh=max(0.05,(home_for+away_against)/2)
    la=max(0.05,(away_for+home_against)/2)
    ph=[poisson(k,lh) for k in range(13)]
    pa=[poisson(k,la) for k in range(13)]
    total=sum(x*y for x in ph for y in pa)
    h=sum(ph[i]*pa[j] for i in range(13) for j in range(13) if i>j)/total
    d=sum(ph[i]*pa[i] for i in range(13))/total
    a=1-h-d
    over=sum(ph[i]*pa[j] for i in range(13) for j in range(13) if i+j>=3)/total
    return h,d,a,over,lh,la

def api_get(path, token, params=None):
    try:
        response = requests.get(
            'https://api.football-data.org/v4/' + path,
            headers={'X-Auth-Token': token.strip()},
            params=params, timeout=25)
    except requests.RequestException as exc:
        raise ValueError('Falha de conexão com o provedor. Tente novamente.') from exc
    status = response.status_code
    if status == 401:
        raise ValueError('HTTP 401: chave inválida ou não reconhecida.')
    if status == 403:
        raise ValueError('HTTP 403: competição ou temporada sem acesso neste plano.')
    if status == 404:
        raise ValueError('HTTP 404: competição não encontrada no provedor.')
    if status == 429:
        raise ValueError('HTTP 429: limite de requisições atingido. Aguarde.')
    if status >= 400:
        raise ValueError(f'HTTP {status}: o provedor recusou a consulta.')
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError('O provedor devolveu uma resposta que não é JSON.') from exc


def get_matches(day, competition, token):
    # A API usa datas UTC; buscar uma margem e filtrar no horário de Brasília.
    start = (day - timedelta(days=1)).isoformat()
    end = (day + timedelta(days=1)).isoformat()
    payload = api_get(f'competitions/{competition}/matches', token,
                      {'dateFrom': start, 'dateTo': end})
    games = payload.get('matches', [])
    if not isinstance(games, list):
        raise ValueError('Resposta inesperada da API: campo matches ausente.')
    selected = []
    for game in games:
        raw = game.get('utcDate')
        if not raw:
            continue
        try:
            utc = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            local = utc.astimezone(ZoneInfo('America/Sao_Paulo'))
        except (ValueError, TypeError):
            continue
        if local.date() == day:
            selected.append((local, game))
    return sorted(selected, key=lambda item: item[0]), len(games)


def load_token():
    # O segredo salvo no Streamlit Cloud tem prioridade; nunca o exibir.
    try:
        return str(st.secrets.get('FOOTBALL_DATA_TOKEN', '')).strip()
    except Exception:
        return os.getenv('FOOTBALL_DATA_TOKEN', '').strip()

init_db()
st.title('⚽ Radar Esportivo IA')
st.caption('MVP local • Dados reais quando conectados à API • Probabilidades ilustrativas calculadas apenas com médias informadas')
with st.sidebar:
    st.header('Configurações')
    token=load_token()
    if token:
        st.success('Chave configurada no servidor.')
    else:
        st.warning('Configure FOOTBALL_DATA_TOKEN em Secrets do Streamlit.')
    st.caption('Gratuito sujeito a limites de competições e requisições. Nunca compartilhe seu token.')
    league=st.selectbox('Campeonato',list(COMPETITIONS))
    day=st.date_input('Data',value=datetime.now(ZoneInfo('America/Sao_Paulo')).date())
    st.info('Libertadores e algumas ligas podem não estar disponíveis no plano gratuito. A aplicação mostrará a restrição.')

t1,t2,t3=st.tabs(['📅 Jogos automáticos','✍️ Análise manual','📚 Histórico'])
with t1:
    st.subheader('Jogos por data e campeonato')
    if st.button('Buscar partidas',type='primary'):
        if not token:
            st.warning('Insira seu token da API na barra lateral para consultar jogos reais.')
        else:
            try:
                games, raw_count = get_matches(day, COMPETITIONS[league], token)
                st.caption(f'Consulta concluída • HTTP 200 • {raw_count} registros na janela UTC • {len(games)} partidas na data de Brasília')
                if not games:
                    st.info('Nenhuma partida encontrada nesta data para esta competição no provedor. Isso não significa que não existam jogos em outras fontes.')
                for local, g in games:
                    h = (g.get('homeTeam') or {}).get('name') or 'Mandante a definir'
                    a = (g.get('awayTeam') or {}).get('name') or 'Visitante a definir'
                    score = (g.get('score') or {}).get('fullTime') or {}
                    result = ''
                    if score.get('home') is not None and score.get('away') is not None:
                        result = f" • {score['home']} x {score['away']}"
                    st.write(f"**{h} × {a}** • {local:%d/%m/%Y %H:%M} (Brasília) • {g.get('status','')}{result}")
                st.caption('Esta consulta lista jogos; não cria previsões sem estatísticas históricas suficientes.')
            except (requests.RequestException,ValueError) as e:
                st.error(f'Não foi possível consultar: {e}')
with t2:
    st.subheader('Estimativa estatística manual (Poisson)')
    st.warning('Insira médias reais verificadas dos últimos jogos. Valores iniciais são apenas exemplos e NÃO representam equipes reais.')
    c1,c2=st.columns(2)
    with c1:
        home=st.text_input('Time mandante','Time A')
        hf=st.number_input('Mandante: gols marcados por jogo (em casa)',0.0,8.0,1.5,0.1)
        ha=st.number_input('Mandante: gols sofridos por jogo (em casa)',0.0,8.0,1.0,0.1)
    with c2:
        away=st.text_input('Time visitante','Time B')
        af=st.number_input('Visitante: gols marcados por jogo (fora)',0.0,8.0,1.1,0.1)
        aa=st.number_input('Visitante: gols sofridos por jogo (fora)',0.0,8.0,1.4,0.1)
    source=st.text_input('Fonte e período das médias (recomendado)','')
    if st.button('Calcular análise',type='primary'):
        h,d,a,o,lh,la=estimate(hf,ha,af,aa)
        st.session_state['last']=(home,away,h,d,a,o,lh,la,source)
    if 'last' in st.session_state:
        home,away,h,d,a,o,lh,la,source=st.session_state['last']
        x,y,z=st.columns(3)
        x.metric(f'Vitória {home}',f'{h:.1%}')
        y.metric('Empate',f'{d:.1%}')
        z.metric(f'Vitória {away}',f'{a:.1%}')
        st.metric('Mais de 2,5 gols',f'{o:.1%}')
        st.write(f'Gols esperados pelo modelo: **{home}: {lh:.2f}** | **{away}: {la:.2f}**')
        st.info('Modelo simplificado, sem ajuste para elenco, lesões, mando além das médias, correlação de gols ou qualidade dos adversários. Não calcula escanteios/cartões sem dados específicos. Não indica aposta.')
        if st.button('Salvar análise'):
            with sqlite3.connect(DB) as db:
                db.execute('INSERT INTO analises(criado,jogo,origem,casa,empate,fora,over25,observacao) VALUES(?,?,?,?,?,?,?,?)',(datetime.now().isoformat(timespec='seconds'),f'{home} x {away}',source,h,d,a,o,'Poisson demonstrativo'))
            st.success('Análise salva localmente.')
with t3:
    with sqlite3.connect(DB) as db:
        rows=db.execute('SELECT criado,jogo,origem,casa,empate,fora,over25 FROM analises ORDER BY id DESC LIMIT 100').fetchall()
    if rows:
        st.dataframe([{'Data':r[0],'Jogo':r[1],'Fonte':r[2],'Casa':f'{r[3]:.1%}','Empate':f'{r[4]:.1%}','Fora':f'{r[5]:.1%}','Over 2,5':f'{r[6]:.1%}'} for r in rows],use_container_width=True)
    else: st.info('Nenhuma análise salva ainda.')
