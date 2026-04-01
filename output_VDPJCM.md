## Fitxa
- **Nom:** VDPJCM
- **Codi:** VDP2-681
- **Data definició:** 2026-03-16

## 1. Objectiu
Integrar el videoporter d'ABREBOX dins de la solució JCM/Motion per gestionar-lo des de CloudAssistant i HONOA, vendre'l sota marca JCM i adaptar-ne el model de negoci i packaging per sortir al mercat.

## 2. Abast
### Inclou
- Integració del videoporter ABREBOX dins de CloudAssistant per a la seva gestió.
- Trasllat de funcionalitats de l'app ABREBOX a l'app HONOA/JCM.
- Gestió d'usuaris del videoporter i de tres tipus de llicències: individual, dual i familiar.
- Creació d'un nou tipus d'instal·lació de videoporter separat de les instal·lacions normals/HONOADOOR.
- Canvis a l'app mòbil per rebre trucades, obrir portes, gestionar relés principals i secundaris, notificacions i configuracions associades.
- Integració de proximitat perquè els tags JCM puguin usar-se també amb el videoporter, inicialment llegint UID i més endavant informació encriptada.
- Rebranding del producte, software, packaging i materials a marca JCM/Jonoa.
### Fora d'abast
- No es faran desenvolupaments per redissenyar o millorar profundament la solució; la prioritat és integrar, no desenvolupar.
- No s'inclourà el Market de l'app d'ABREBOX.
- No es gestionaran grups ni es farà un mix d'equips en aquesta fase.
- Una instal·lació de videoporter no treballarà a la mateixa instal·lació amb HONOADOOR, bases ni altres equips.
- L'usuari no podrà treballar indistintament amb l'app d'ABREBOX i la de JCM sobre el mateix cas; serà una o l'altra.

## 3. Entregables
- Integració del videoporter dins de CloudAssistant amb gestió d'instal·lacions específiques de videoporter.
- Nous dashboards, pantalles i fluxos de gestió d'usuaris i llicències (individual, dual, familiar).
- Implementació a l'app React/Android de funcionalitats de videoporter: trucades, notificacions, relés, subusuaris i configuracions.
- Integració de relés externs/RS485 amb suport de fins a quatre relés per accés vinculat.
- Validació de SIM/connectivitat per a la solució connectada del videoporter.
- Personalització i rebranding del hardware, software, etiquetes i packaging a marca JCM/Jonoa.
- Solució de proximitat perquè el videoporter llegeixi tags compatibles, inicialment via UID amb canvi de mòdul NFC.

## 4. Planificació inicial
### Resum
El projecte es planteja com una integració ràpida d'ABREBOX dins l'ecosistema JCM, prioritzant time-to-market per sobre de redissenys profunds. El calendari apunta a tenir el producte llest per vendre al juny de 2026 i iniciar vendes al setembre de 2026. El treball inclou back-end, front-end, app mòbil, validació de SIM, proximitat i rebranding amb dependències externes del fabricant i d'un proveïdor d'apps.
### Fites
- Definició tècnica del projecte — 2026-03-16
- Disponibilitat per poder vendre — 2026-06-30
- Inici de vendes — 2026-09-01
- Tancament d'Inception

## 5. Esforç inicial
- **Estimació:** story points

## 6. Stakeholders
- Joan Bonache
- Jordi Beringues
- David Clos
- Eloi Baulenas
- David Villanueva
- Gil Prat
- José Montón
- Salvador Farràs
- Stefano Travani
- Marketing
- Logística / aprovisionament
- Fabricant/proveïdor xinès del videoporter

## 7. Dependències
- Canvi del mòdul NFC/hardware del videoporter per suportar lectura compatible amb Desfire/Spire Lite o almenys UID.
- Resposta i suport del fabricant per definir el protocol sèrie si JCM acaba integrant lector propi.
- Validació de SIM i costos de connectivitat per a la solució connectada.
- Pressupost i disponibilitat del proveïdor extern de l'app (Carbó).
- Dissenys d'interfície i feina de back-end/front-end/apps per completar la integració.
- Decisions de màrqueting i logística per al rebranding de producte i stock existent.

## 8. Riscos inicials
- Risc de no arribar a termini perquè la data objectiu de juny és ajustada i ja s'ha anat movent.
- Risc tècnic perquè el mòdul NFC actual no llegeix Desfire i pot requerir canvi de hardware.
- Risc d'incompatibilitat o dispersió a instal·lacions ja desplegades si canvia el lector o la plaqueta de proximitat.
- Risc de manca de pressupost tancat i d'incertesa en les estimacions de l'app externa.
- Risc de coexistència amb stock i equips actuals amb marca ABREBOX mentre es fa la transició a JCM.

## 9. Punts oberts
- Quina data exacta de juny és el compromís real de disponibilitat/producció?
- El fabricant acceptarà canviar el mòdul NFC o caldrà que JCM desenvolupi la seva pròpia solució?
- Com s'implementarà a la interfície la gestió de botons/portes secundàries, ja que ABREBOX no ho modela com JCM.
- Quin branding definitiu es posarà al producte i al software (JCM, Jonoa, JonoaCall, etc.)?
- Com es gestionarà el stock existent i la transició logística dels equips actuals amb marca ABREBOX?
- S'inclourà en aquesta entrega l'eliminació de Hikvision per evitar problemes de mida/executables?

## 10. Resum executiu
VDPJCM és un projecte d'integració del videoporter d'ABREBOX dins l'ecosistema JCM per comercialitzar-lo sota marca pròpia i gestionar-lo des de CloudAssistant i HONOA. L'abast inclou noves instal·lacions de videoporter, gestió d'usuaris i llicències, funcionalitats d'app mòbil, proximitat amb tags JCM i rebranding de producte i packaging. La prioritat declarada és integrar ràpidament, evitant desenvolupaments profunds, amb objectiu de disponibilitat comercial al juny de 2026 i inici de vendes al setembre. Els principals riscos són el calendari molt ajustat, la dependència del fabricant per al mòdul NFC/protocol, la validació de SIM i la manca d'un pressupost tancat per a part del desenvolupament extern.

## 11. Fonts utilitzades
- 260316_Definició_tècnica_VDJCM_MVS1_(Integració_Abrebox)_[VDP2-681]~.md
- 260323_Proximitat.md
