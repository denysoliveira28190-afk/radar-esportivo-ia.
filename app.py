import os, math, sqlite3
from datetime import date, datetime
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

def get_matches(day,competition,token):
    headers={'X-Auth-Token':token}
    response=requests.get('https://api.football-data.org/v4/matches',headers=headers,params={'dateFrom':day.isoformat(),'dateTo':day.isoformat(),'competitions':competition},timeout=18)
    if response.status_code==403:
        raise ValueError('Esta competição ou temporada não está liberada no seu plano da API.')
    if response.status_code==429:
        raise ValueError('Limite de requisições atingido. Tente novamente mais tarde.')
    response.raise_for_status()
    return response.json().get('matches',[])

init_db()
st.title('⚽ Radar Esportivo IA')
st.caption('MVP local • Dados reais quando conectados à API • Probabilidades ilustrativas calculadas apenas com médias informadas')
with st.sidebar:
    st.header('Configurações')
    token=st.text_input('Token football-data.org',value=os.getenv('FOOTBALL_DATA_TOKEN',''),type='password')
    st.caption('Gratuito sujeito a limites de competições e requisições. Nunca compartilhe seu token.')
    league=st.selectbox('Campeonato',list(COMPETITIONS))
    day=st.date_input('Data',value=date.today())
    st.info('Libertadores e algumas ligas podem não estar disponíveis no plano gratuito. A aplicação mostrará a restrição.')

t1,t2,t3=st.tabs(['📅 Jogos automáticos','✍️ Análise manual','📚 Histórico'])
with t1:
    st.subheader('Jogos por data e campeonato')
    if st.button('Buscar partidas',type='primary'):
        if not token:
            st.warning('Insira seu token da API na barra lateral para consultar jogos reais.')
        else:
            try:
                games=get_matches(day,COMPETITIONS[league],token)
                if not games: st.info('Nenhuma partida retornada nesta data/competição.')
                for g in games:
                    h=g.get('homeTeam',{}).get('name','Mandante')
                    a=g.get('awayTeam',{}).get('name','Visitante')
                    st.write(f"**{h} × {a}** — {g.get('utcDate','')} UTC — {g.get('status','')}")
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
