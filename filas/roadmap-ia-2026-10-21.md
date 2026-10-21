# Fila: roadmap de IA (recebido em 21/10/2026)

Cópia integral do pedido do usuário, para nada se perder. Estado operacional de cada item: `_staging/raw/STATUS.md`
do tech-vault (`[~]` = aguardando adaptador do extrator; `[ ]` = pronto para o lote; `[x]` = extraído).
Regras do pedido: ingerir por fase e rodar o indexador ao fim de cada uma; livros pagos ficam fora (só documentação,
cursos abertos e papers); conferir no Microsoft Learn a situação do AI-900 e do DP-100 antes de usar como trilha.

---

Fase 1: Fundamentos → `50-ai-engineering/fundamentos`
Primeiro, porque todo o resto se apoia nisso.

* [Google Machine Learning Crash Course](https://developers.google.com/machine-learning/crash-course): ML clássico, do zero.
* [Dive into Deep Learning (d2l.ai)](https://d2l.ai): deep learning com licença aberta.
* [Hugging Face LLM Course](https://huggingface.co/learn/llm-course): transformers, fine-tuning e LLMs.
* [scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html): referência prática de algoritmos.

Fase 2: Claude como expert → `50-ai-engineering/claude`
Ganho imediato no seu dia a dia e no time de IA da Lab2dev.

* [Documentação Claude](https://docs.claude.com): API, modelos, ferramentas e prompt engineering.
* [Anthropic Courses (GitHub)](https://github.com/anthropics/courses): prompt engineering, tool use e avaliação, em notebooks.
* [Anthropic Academy](https://anthropic.skilljar.com): cursos de Claude Code, MCP e Agent Skills.
* [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): os padrões de agentes, independentes de fornecedor.
* [Model Context Protocol](https://modelcontextprotocol.io): especificação e guias de MCP.

Fase 3, trilha A: IA na AWS → `30-aws/ai`
A espinha é a certificação [Generative AI Developer Professional, AIP-C01 (guia oficial)](https://docs.aws.amazon.com/aws-certification/latest/ai-professional-01/ai-professional-01.html). Antes dela vêm o AI Practitioner e o ML Engineer Associate. O ML Specialty foi aposentado em 31/03/2026.

* [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/): modelos, Knowledge Bases (RAG), Agents e Guardrails.
* [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/): runtime de agentes em produção.
* [Amazon SageMaker](https://docs.aws.amazon.com/sagemaker/): treino, deploy e pipelines de ML.
* [Well-Architected: Generative AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/) e [Machine Learning Lens](https://docs.aws.amazon.com/wellarchitected/latest/machine-learning-lens/): a visão de arquiteto.

Fase 3, trilha B: IA na Azure → `40-azure/ai`
A espinha é a certificação AI-103, Developing AI Apps and Agents on Azure, que substituiu a AI-102 (aposentada em 30/06/2026). O conteúdo vem do [curso oficial AI-103T00](https://learn.microsoft.com/training/courses/ai-103t00).

* [Microsoft Foundry](https://learn.microsoft.com/azure/ai-foundry/): modelos (incluindo Azure OpenAI), agentes e avaliação.
* [Azure Architecture Center: AI e ML](https://learn.microsoft.com/azure/architecture/ai-ml/): arquiteturas de referência, incluindo RAG.
* [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/): o sucessor do Semantic Kernel e do AutoGen.
* [Azure Machine Learning](https://learn.microsoft.com/azure/machine-learning/): ML clássico e MLOps na Azure.

Fase 3, trilha C: lacunas no BTP → `20-sap/business-ai-platform`

* [Document Information Extraction](https://help.sap.com/docs/document-information-extraction): zero notas hoje.
* [SAP HANA Cloud Vector Engine](https://help.sap.com/docs/hana-cloud-database/sap-hana-cloud-sap-hana-database-vector-engine-guide): só 3 notas hoje, e é a base de RAG no BTP.
* [SAP AI Core](https://help.sap.com/docs/sap-ai-core): o lado de ML clássico (treino e serving), que complementa o Generative AI Hub que você já tem.
* SAP-RPT-1, o modelo de fundação da SAP para dados tabulares. Ainda não tenho o link oficial; vale buscar no SAP Help.

Fase 4: n8n → `50-ai-engineering/n8n`

* [Documentação n8n](https://docs.n8n.io): nós, credenciais e expressões.
* [LangChain no n8n](https://docs.n8n.io/build/integrate-ai/langchain-in-n8n): agentes, memória, ferramentas e RAG.
* [Cursos oficiais n8n](https://docs.n8n.io/courses/): níveis 1 e 2.
* [Self-hosting](https://docs.n8n.io/hosting/): para rodar no ambiente da Lab2dev.

Fase 5: MLOps → `60-devops-platform/mlops`
Por último, porque depende das fases 1 e 3.

* [Google Cloud: MLOps, continuous delivery and automation pipelines](https://cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning): o modelo de maturidade de referência.
* [Made With ML](https://madewithml.com): MLOps de ponta a ponta, aberto.
* [MLOps Zoomcamp (DataTalksClub)](https://github.com/DataTalksClub/mlops-zoomcamp): prática com MLflow, orquestração e monitoramento.
* [Azure MLOps v2](https://github.com/Azure/mlops-v2): acelerador oficial da Microsoft.
* [Hidden Technical Debt in Machine Learning Systems (NeurIPS 2015)](https://papers.nips.cc/paper/5656-hidden-technical-debt-in-machine-learning-systems): o paper clássico do tema.

Antes de começar:

* Ingira por fase e rode o indexador ao fim de cada uma, para o grafo ligar as notas.
* Livros pagos ficam fora. Só documentação, cursos abertos e papers.
* Ainda não confirmei a situação atual do AI-900 e do DP-100 na Azure; confira no Microsoft Learn antes de usar como trilha.

Sources:

* [AWS Certified Generative AI Developer – Professional (AIP-C01), guia oficial](https://docs.aws.amazon.com/aws-certification/latest/ai-professional-01/ai-professional-01.html)
* [What’s changing with AWS certifications in 2026 (Training Camp)](https://trainingcamp.com/articles/whats-changing-with-aws-certifications-in-2026-and-what-to-take-instead/)
* [AI-102 vs AI-103 in 2026 (Open Exam Prep)](https://open-exam-prep.com/blog/ai-102-vs-ai-103-which-exam-2026)
* [AI-103T00 (Microsoft Learn)](https://learn.microsoft.com/training/courses/ai-103t00)
* [LangChain in n8n (n8n Docs)](https://docs.n8n.io/build/integrate-ai/langchain-in-n8n)
* [Anthropic Courses (GitHub)](https://github.com/anthropics/courses)
