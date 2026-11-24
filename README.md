# Ferramenta Auxiliar de Planejamento SLOP

Aplicativo Streamlit de apoio ao planejamento, sem substituir a doutrina, as fontes oficiais ou o julgamento do MSL.

## Abas adicionadas

- **Salto sobre o Alvo (DKVA):** reutiliza o Windgram processado, permite selecionar camadas, calcula velame e queda livre, edita azimute/comprimento de cada segmento, apresenta os PS/limites, mapa satelital e downloads KMZ por modalidade. A aeronave e os parâmetros dos paraquedas são editáveis. O eixo de pouso verde e o bloco de aeródromo/diferença altimétrica foram mantidos.
- **Divisão das Equipes:** permite editar saltadores, ordenar por modalidade, trabalho, velame e peso, atribuir alturas em passos de 500 ft respeitando mínimos, e exportar CSV/XLSX. Informe o máximo por passagem definido pelo MSL.
- **Ajuste de DAA:** reutiliza as altitudes e a pressão disponíveis na sessão, permite edição/consulta de PS e calcula ajustes para Cypres, Vigil e variantes militares.
- **Planejamento SLOp:** o acesso remoto depende de implantação privada configurada; a execução local permanece restrita a loopback por padrão.

## Estrutura

- `app.py`: aplicativo original e navegação.
- `planning_ui.py`: telas de DKVA, divisão de equipes e DAA.
- `calc_dkva.py`: cálculos DKVA e destinos WGS-84.
- `daa.py`: funções puras de ajuste de altímetro/DAA.
- `equipes.py`: ordenação e distribuição de alturas.
- `kml_export.py`: serialização de KMZ.
- `tests/`: testes de cálculos, geometrias, KML e cenários de equipes.
- Os arquivos de referência fornecidos ficam na raiz desta pasta de trabalho.

## Execução local

1. Use Python 3.12 (ou versão compatível com as dependências).
2. Instale: `python -m pip install -r requirements.txt`.
3. O arquivo `.streamlit/secrets.toml` está no `.gitignore`; nunca o envie ao GitHub. O webhook permanece desativado por padrão no modo local. Não substitua o arquivo existente pela amostra.
4. Execute: `python -m streamlit run app.py --server.address 127.0.0.1`.
5. Abra `http://localhost:8501`. O servidor está vinculado a `127.0.0.1` e, por padrão, só aceita conexões neste computador.
6. Teste: `python -m pytest -q`.

## Redesign Rampa

- **Painel da Missão** concentra a identificação da ZL, altitude do alvo, situação do Windgram e distâncias DKVA já calculadas; não recalcula nem altera resultados.
- O mapa DKVA mantém os segmentos padronizados e mostra legenda acessível: velame aberto (vermelho), queda livre (branco), arrasto (azul), dispersão (amarelo) e margem (preto).
- O tema, as cores e as fontes ficam em `.streamlit/config.toml`; o CSS responsivo centralizado fica em `assets/estilo.css`.
- As imagens locais estão em `assets/`. Para substituí-las, mantenha os nomes dos arquivos. A foto da rampa deve permanecer sem cortes e com o crédito “Foto: Exército Brasileiro”.
- A tipografia IBM Plex Sans/Mono é carregada do Google Fonts; o navegador faz uma solicitação ao provedor de fontes, sem enviar dados de missão. Para uma política sem requisições externas de fontes, use uma fonte local ou padrão do sistema.

## Acesso local somente neste computador

Por padrão, o app só inicia com bind loopback (`127.0.0.1`, `::1` ou `localhost`). Isso impede conexões de outros computadores, mas não identifica uma pessoa; qualquer pessoa ou processo com acesso à sua sessão do Windows pode abrir o painel. Proteja sua conta do Windows e não encaminhe a porta nem use túnel.

## Publicação privada no Streamlit Community Cloud

O deploy ainda depende das ações da conta GitHub/Streamlit do proprietário. O diretório local precisa ser enviado a um repositório **privado**; coordenadas das ZLs no código foram autorizadas pelo usuário para esse repositório privado. Antes do primeiro deploy:

1. Confirme que o repositório GitHub está privado e que `.streamlit/secrets.toml`, credenciais e dados reais de missão não estão incluídos.
2. Crie o app no Streamlit Community Cloud apontando para o repositório privado, branch e `app.py`.
3. Nas configurações **Secrets** do app hospedado, configure:

   ```toml
   WEBHOOK_GOOGLE_SHEETS = "URL_DO_WEBHOOK"

   [hosting]
   allow_non_loopback = true

   [webhook]
   enabled = true
   ```

   O valor de `WEBHOOK_GOOGLE_SHEETS` é segredo; use somente a área de Secrets do Streamlit, não um commit.
4. Nas configurações de compartilhamento, marque **Only specific people can view this app** e convide cada pessoa pelo e-mail. Não mude para app público. Remova os convidados quando o acesso deixar de ser necessário.
5. Faça um teste com dados fictícios e confirme a conectividade do webhook antes de usar dados de missão.

O app aceita bind não-loopback somente quando `hosting.allow_non_loopback` está explicitamente como o booleano `true`. A restrição de visualização é feita pelo modo privado e pela lista de convidados do Streamlit Cloud; o app não adiciona uma segunda autenticação OIDC.

O Community Cloud processará dados enviados pelo usuário e o webhook, se habilitado, enviará ação, localidade e coordenadas do alvo e do aeródromo ao destino configurado. A organização autorizou hospedagem desses dados no cenário selecionado; confirme a política e restrinja o acesso também no serviço que recebe o webhook.

## Dados externos e webhook

- Conforme autorizado, o app mantém as consultas de busca de localidade (Nominatim/Open-Meteo) e altitude/pressão (Open-Meteo/Open-Elevation); os tiles Esri revelam ao provedor a área aproximada exibida no mapa.
- O webhook fica **desativado por padrão** localmente (`[webhook].enabled = false`). Quando ativado, gerar KMZ do Velame Aberto, KMZ do DKVA ou Folder do Piloto envia ação, localidade e coordenadas do alvo e do aeródromo.
- O proprietário autorizou manter no repositório privado as coordenadas das ZLs pré-cadastradas; isso não autoriza incluir coordenadas de missões em commits, capturas ou logs.

## Premissas e itens [A CONFIRMAR]

- `VA_Nariz!B27` tem `#REF!`; a saída de altura mínima para retorno não foi implementada.
- A base de comandamento das equipes é editável e marcada `[A CONFIRMAR]`; o máximo por passagem deve ser informado pelo MSL.
- As margens e segmentos são editáveis. Boca do Cone fica bloqueada se o comprimento do velame não cair em uma faixa configurada.
- A versão local de `geomag` contém `WMM-2015`; não foi atualizada sem autorização. A declinação é editável e precisa ser confirmada com o NCEI.
- As divergências de tabelas de aeronave nas abas antigas foram preservadas; a nova aba DKVA usa sua configuração central.
- A leitura dos KMZ de referência foi feita; ainda não foi verificada a abertura no Google Earth.
- O diretório de trabalho não tem repositório Git nem Git CLI disponível; ainda não foi criado repositório remoto, branch, commit ou app hospedado.
