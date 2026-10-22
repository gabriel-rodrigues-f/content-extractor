# Fila: SAP Task Center (recebido em 22/10/2026)

Cópia integral do pedido do usuário. Estado de cada item: `_staging/raw/STATUS.md` do tech-vault, grupo "Task Center".

---

1. Núcleo do Task Center (pasta nova `20-sap/btp/task-center/`)

* [Guia oficial, PDF de 14/07/2026](https://help.sap.com/doc/ab1cc29fb9aa41889779ce4f699142cd/Cloud/en-US/TaskCenter_PUBLIC_EN_1.pdf): o guia inteiro. Seções essenciais: Initial Setup, Destinations to Task Providers (uma página por provedor), Global User ID, Task Center Administration, Export API, Troubleshooting.
* [Integrate SAP Task Center with Task Providers](https://help.sap.com/docs/task-center/sap-task-center/destinations-to-task-providers): dessa página, as subpáginas de S/4HANA Cloud Public Edition, Ariba e SAP Build Process Automation.
* [SBPA no mesmo subaccount](https://help.sap.com/docs/TASK_CENTER/08cbda59b4954e93abb2ec85f1db399d/f9c57ee5a66349dbbeeda822cecd2fa2.html) e [em subaccount diferente](https://help.sap.com/docs/task-center/sap-task-center/work-with-sap-build-process-automation-tasks-from-remote-subaccount).
* [FAQ do Task Center](https://pages.community.sap.com/topics/task-center/faq): provedores suportados, limite de terceiros, licenciamento.
* [Arquitetura de referência](https://architecture.learning.sap.com/docs/ref-arch/c1e07f) e a [versão atual](https://architecture.learning.sap.com/docs/ref-arch/0245473a99), com o `.drawio`.
* [Guided Answers do Task Center](https://ga.support.sap.com/dtp/viewer/index.html#/tree/3109/actions/47627) para troubleshooting.

2. Identidade (complementa a pasta de SSO já ingerida)

* [Global User ID in Integration Scenarios](https://help.sap.com/docs/cloud-identity/system-integration-guide/global-user-id-in-integration-scenarios).
* No guia do IPS: os cenários de provisionamento IAS → S/4HANA Cloud Public Edition e IAS → Ariba, porque é o IPS que leva o Global User ID até cada provedor.

3. Lado dos provedores SAP

* [Configuração de tasks no S/4HANA Cloud Public](https://help.sap.com/docs/SAP_S4HANA_CLOUD/0f69f8fb28ac4bf48d2b57b9637e81fa/bd24da7d1d174b949e2136089bf307d9.html): cenário de comunicação do Task Center (SAP_COM_0501, confirmar no texto) e os workflows de compras que aparecem no inbox.
* Ariba: a página do guia do Task Center sobre Ariba e a documentação de integração do Ariba com IAS. Guardar o aviso de que Ariba só vem na fase 2 da EPR.
* [Blog de setup com S/4HANA Cloud](https://blogs.sap.com/2022/02/24/setup-sap-task-center-with-sap-s-4hana-cloud/) e o [overview de configuração](https://community.sap.com/t5/technology-blog-posts-by-members/sap-task-centre-configuration-overview/ba-p/14470964).

4. Ponte para os terceiros

* [Task Center para ECC via conector terceiro](https://community.sap.com/t5/technology-blog-posts-by-members/implementation-of-sap-task-center-for-erp-ecc-systems-non-s-4hana-using/ba-p/14080345): é o padrão a replicar para Unifier e LG.
* [Configurar tarefas do SBPA no Task Center](https://community.sap.com/t5/technology-blog-posts-by-sap/learn-how-to-configure-sap-build-process-automation-tasks-for-sap-task/ba-p/13576849) e [Integrate and Extend with SBPA](https://architecture.learning.sap.com/docs/ref-arch/b86487).
* Do guia do SBPA: Workflow Management API (criar instância, user task, completar tarefa) e forms de aprovação.
* Documentação de API do Oracle Primavera Unifier (REST: workflows, business processes, records) e da LG Lugar de Gente, assim que o Felipe mandar. Ingerir como `30-third-party/oracle-unifier/` e `30-third-party/lg-lugar-de-gente/`.

5. Canal móvel

* Guia do SAP Mobile Start: configuração, To-Dos do Task Center, requisitos (SAP Start ou Work Zone standard), MDM e distribuição. A [learning journey](https://learning.sap.com/learning-journeys/Setting-Up-SAP-Build-Work-Zone-standard-edition-and-SAP-Mobile-Start-with-SAP-S-4HANA/introducing-sap-task-center) cobre o caminho inteiro com S/4HANA.
* [FAQ de Mobile Experience](https://pages.community.sap.com/topics/mobile-experience/faq).

6. Comercial

* [Task Center no Discovery Center](https://discovery-center.cloud.sap/serviceCatalog/sap-task-center?region=all) e a [mission de inbox central](https://discovery-center.cloud.sap/missiondetail/3774/3813/).
