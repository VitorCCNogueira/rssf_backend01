# Laboratorio E220 e coexistencia com o no instalado

O POST `/api/salvar_dados` preserva o formato legado. Lotes somente sao aceitos para o par explicitamente configurado em `LAB_SENSOR_ID` e `LAB_GATEWAY_ID`. O mesmo ID em outro gateway continua legado. `LAB_SENSOR_ID` vazio desabilita lotes; nao use o ID dos testes como configuracao real.

## Contrato

O receptor de laboratorio deve incluir `gateway_id: "gateway_lab_01"` no JSON, alem de `senderAddress`, `rssi` opcional e `medicoes`. Cada item contem `idade_min` e as seis chaves `temp_ds1` a `temp_ds6`, com numeros finitos ou null. O lote aceita de 1 a 16 itens, idades inteiras distintas entre 0 e 450 minutos, incluindo obrigatoriamente idade zero. Nao misture temperaturas na raiz com `medicoes`.

Neste perfil SEM sensores, todas as temperaturas sao armazenadas como NULL, inclusive sentinelas numericas recebidas do firmware. Nao use esse perfil em um no com sensores reais. RSSI e identidade sao preservados. O backend valida todo o lote antes de gravar, usa uma transacao e retorna 201 com `medicoes_salvas`; entrada invalida retorna 400 sem gravacao e erro de persistencia retorna 500 com rollback.

`data_hora` e o horario UTC do banco menos `idade_min`, com uma referencia por lote. Sao estimativas dos ciclos, nao timestamps exatos de transmissao. O item de idade zero representa o contato mais recente. O firmware nao envia tensao da bateria, identificador de lote nem timestamps absolutos: este painel acompanha comunicacao, nao calcula carga, consumo, quantidade exata de pacotes ou entrega garantida. Reenvios podem duplicar amostras.

## Status e historico

Legado: online antes de 60 minutos, instavel de 60 ate antes de 180, offline a partir de 180. Laboratorio: 540/1440 minutos, configuraveis separadamente. Timestamps mais de um minuto no futuro ficam desconhecidos. Falha de consulta nao confirma conectividade.

`GET /api/dashboard` retorna leituras mais recentes, perfis, status e horario do servidor em uma consulta ao banco. Respostas nao devem ser cacheadas. Datas sao ISO 8601 UTC com Z. Filtros `inicio`/`fim` exigem ambos, em ordem; offsets sao convertidos para UTC, datas sem offset sao interpretadas como UTC.

`GET /api/medicoes/historico?sensor_id=...&gateway_id=...` retorna ate 1000 intervalos, com medias de temperaturas validas e RSSI, `sample_count`, `total`, `bucket_seconds` e `aggregated`. O endpoint de estatisticas calcula os valores exatos sobre todas as amostras validas do escopo, independente da agregacao do grafico. Sem datas, ambos consultam todo o historico daquele ponto. O CSV do dashboard exporta a serie exibida (analitica), podendo conter medias; para exportacao bruta use o endpoint legado de medicoes por sensor com limite explicito ou por intervalos de datas.

## Ativacao e rollback

1. Confirme o senderAddress real no serial do transmissor e no payload do receptor; configure esse numero em LAB_SENSOR_ID. Configure o mesmo LAB_GATEWAY_ID no backend e no JSON do receptor. O receptor atual precisa dessa identificacao explicita antes de enviar lotes.
2. Confira que a tabela usa `data_hora TIMESTAMP`, `sensor_id SMALLINT UNSIGNED`, temperaturas anulaveis e o indice `(sensor_id, gateway_id, data_hora, id)`. Esses itens ja constam do schema e migracoes existentes. Esta mudanca nao exige nova migracao, mas uma instalacao desatualizada precisa aplicar as migracoes existentes apos backup. Nao reescreva horarios historicos. Se a coluna real for DATETIME, revise o fuso antes de publicar.
3. Defina explicitamente STATUS_ONLINE_MINUTES=60 e STATUS_OFFLINE_MINUTES=180, principalmente se o ambiente herdou 540/1440 da branch anterior. Preencha as variaveis MYSQL* conforme o ambiente. A conexao usa sessao UTC.
4. Publique primeiro o backend e valide leitura/status do no instalado. Depois publique o frontend correspondente (ele depende dos endpoints novos). Ative o receptor de laboratorio por ultimo. Verifique um lote aceito, temperaturas NULL, isolamento entre pontos, status e historico geral.
5. Para rollback, interrompa os envios do laboratorio, restaure primeiro o frontend e depois o backend. As linhas inseridas nao sao removidas automaticamente.

A publicacao destes PRs nao faz deploy. Nao foi medida latencia em producao. A consulta consolidada reduz requisicoes duplicadas e o historico limitado reduz o volume transferido; estatisticas gerais ainda dependem do volume/indexacao do banco.

O firmware de radio nao foi alterado: revise antes do ensaio a validacao da configuracao E220 e o descarte do buffer apos falha de envio. Os testes de backend/frontend nao comprovam autonomia de bateria nem entrega pelo radio.
