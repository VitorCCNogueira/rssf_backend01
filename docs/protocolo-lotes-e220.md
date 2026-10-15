# Recebimento de lotes E220

O POST `/api/salvar_dados` aceita o payload legado (temperaturas na raiz) e o novo payload com `senderAddress`, `rssi` opcional, `gateway_id` opcional e uma lista `medicoes`.

Cada item da lista deve conter `idade_min` e as seis chaves `temp_ds1` a `temp_ds6`. Temperaturas aceitam numeros finitos ou null. O lote deve conter de 1 a 16 itens; as idades devem ser inteiros distintos de 0 a 450 minutos. A ordem dos itens nao importa. Nao e permitido misturar temperaturas na raiz com a lista.

Exemplo com duas leituras:

```json
{
  "senderAddress": 44204,
  "rssi": -80,
  "medicoes": [
    {"idade_min": 30, "temp_ds1": 25, "temp_ds2": 26, "temp_ds3": 27, "temp_ds4": 28, "temp_ds5": 29, "temp_ds6": 30},
    {"idade_min": 0, "temp_ds1": 26, "temp_ds2": 27, "temp_ds3": 28, "temp_ds4": 29, "temp_ds5": 30, "temp_ds6": 31}
  ]
}
```

Um lote valido retorna HTTP 201 com `medicoes_salvas`. Cada leitura vira uma linha, com o mesmo no, gateway e RSSI do pacote. O lote inteiro e validado antes da persistencia e gravado em uma unica transacao; falhas provocam rollback e HTTP 500. Um lote invalido retorna HTTP 400 sem gravar nenhuma leitura.

`data_hora` e calculado como CURRENT_TIMESTAMP do banco menos `idade_min`, usando uma unica referencia por lote. Isso preserva a convencao de fuso da sessao MySQL utilizada pelas insercoes legadas, sem migracao de schema. O horario e uma estimativa baseada na chegada do pacote, pois o firmware nao envia um timestamp absoluto. Atrasos de transporte tambem deslocam essa estimativa.

## Status e implantacao

O firmware novo transmite a cada 16 ciclos de 30 minutos (aproximadamente 8 horas). O status global padrao agora e online por menos de 540 minutos, instavel de 540 ate menos de 1440 minutos e offline a partir de 1440 minutos. Os limites sao controlados por `STATUS_ONLINE_MINUTES` e `STATUS_OFFLINE_MINUTES`; exige-se 0 < online < offline. O status continua usando a leitura mais recente.

Instalacoes apenas com firmware legado podem definir 60 e 180 para manter os limites anteriores. Em redes mistas, os limites sao compartilhados: com o padrao novo, detectar falhas dos nos legados leva mais tempo. Reinicie o backend apos mudar as variaveis.

Publique o backend antes de ativar os novos receptores. O formato legado continua aceito. Nenhuma migracao SQL e necessaria.

O protocolo atual nao inclui identificador de lote: reenviar um POST pode duplicar leituras. Esta alteracao nao implementa ACK, retransmissao nem corrige o descarte do buffer no transmissor quando o radio falha.
