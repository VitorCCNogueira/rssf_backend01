# Envio inicial do laboratorio E220

Grave transmissor_paper/transmissor_paper.ino e receptor_paper/receptor_paper.ino desta branch nas duas placas de laboratorio. O firmware legado nao foi alterado.

## Sequencia
1. Configure LAB_SENSOR_ID no backend com o senderAddress real do transmissor (impresso no serial a 115200 baud).
2. Confira LAB_GATEWAY_ID no backend e no receptor: gateway_lab_01 por padrao. Ajuste a rede Wi-Fi do receptor.
3. Ligue primeiro o receptor e aguarde a mensagem de modo NORMAL/aguardando pacotes e a conexao Wi-Fi.
4. Ligue ou reinicie o transmissor. Ele coleta uma leitura e envia imediatamente um Packet do tamanho habitual, com qntd_medicoes=1. O receptor gera um lote com idade_min=0. O backend de laboratorio transforma as temperaturas em NULL.
5. Confira no receptor a mensagem HTTP 201 / Gravacao confirmada pelo backend. Depois confira o ponto no dashboard (atualizacao de aproximadamente 30 segundos).

Sucesso local do E220 nao e ACK do receptor nem confirmacao HTTP. O transmissor nao recebe confirmacao fim a fim. Se o envio inicial nao aparecer, confira ID, gateway, rede e canal; depois reinicie o transmissor com o receptor pronto.

## Cadencia e bateria
O envio inicial esvazia o buffer. Apos isso, o transmissor dorme 30 minutos e acumula 16 novas leituras: o proximo lote sai aproximadamente 8 horas depois, seguido de lotes no mesmo intervalo. Tempo de processamento adiciona pequeno desvio. Acordar do deep sleep nao repete o envio inicial. Reset, regravacao, brownout ou religamento iniciam novo ensaio, descartam o buffer antigo e fazem novo envio inicial. Abrir o monitor serial pode reiniciar certas placas.

Ha um envio extra por inicializacao, portanto registre resets ao comparar autonomia. Nao foi implementada telemetria de tensao da bateria.

Mantida a politica sem ACK/retransmissao: apos uma tentativa de envio o buffer e limpo inclusive em falha local, com aviso no serial. Isso evita reenviar leituras antigas com idade zero, mas pode perder dados. Se a inicializacao falhar, a proxima tentativa automatica e no lote cheio; reinicie manualmente para repetir a verificacao imediata. Este PR nao promete entrega garantida.

## Verificacao
Workflow firmware-e220.yml compila os dois sketches para ESP32 Dev Module. Valide na placa real: envio unico ao ligar, ausencia de envio apos primeiro wake de 30 minutos, lote de 16 apos 8 horas e novo envio ao reiniciar. Testes do backend cobrem lote unitario e lote completo. Compilacao nao substitui teste de radio/energia em bancada.


## Pinagem da PCB RSSF (transmissor e receptor)
Esta revisão usa a pinagem documentada no projeto PCB: TXD do E220 -> GPIO17 (RX do ESP32); RXD do E220 <- GPIO16 (TX do ESP32); AUX -> GPIO5; M0 -> GPIO2; M1 -> GPIO4. Os argumentos de UART passados ao construtor refletem essa orientação. GPIO18 fica sem uso, conforme o esquema da PCB; confira continuidade na sua unidade se ainda existir um fio antigo ligado a D18.

A configuração física da produção foi adicionada no Railway: LAB_SENSOR_ID=21768 e LAB_GATEWAY_ID=gateway_lab_01. O primeiro identifica o transmissor do laboratório, e o segundo deve coincidir com o valor enviado pelo receptor. A imagem de log anterior mostrou o transmissor lendo AUX no GPIO22, incompatível com a PCB; grave ambos os sketches atualizados antes de testar.