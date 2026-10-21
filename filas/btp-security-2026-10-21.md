# Fila: segurança no SAP BTP (recebido em 21/10/2026)

Cópia integral do pedido do usuário. Estado de cada item: `_staging/raw/STATUS.md` do tech-vault, grupo
"BTP Security".

---

Fontes para ingerir:

* 1: [SAP BTP Security Recommendations](https://help.sap.com/docs/btp/sap-btp-security-recommendations-c8a9bb59fe624f0981efa0eff2497d7d/sap-btp-security-recommendations) · [Security Concepts (Administrator’s Guide)](https://help.sap.com/docs/btp/best-practices/security-concepts)
* 2: [SAP BTP Security](https://help.sap.com/docs/btp/sap-business-technology-platform/btp-security) · [Identity and Access Management no BTP](https://help.sap.com/docs/btp/sap-business-technology-platform/introduction-to-identity-and-access-management-on-sap-btp)
* 3: [Principal Propagation](https://help.sap.com/docs/connectivity/sap-btp-connectivity-cf/principal-propagation) · [Configuring Principal Propagation](https://help.sap.com/docs/connectivity/sap-btp-connectivity-cf/configuring-principal-propagation) · [Identity Propagation para HTTPS](https://help.sap.com/docs/connectivity/sap-btp-connectivity-cf/configure-principal-propagation-for-https)
* 4: [Configuring Authorization Policies](https://help.sap.com/docs/cloud-identity-services/cloud-identity-services/configuring-authorization-policies)
* 5: [SAP Credential Store](https://help.sap.com/docs/credential-store)
* 6: [Audit Logs: Retention and Retrieval APIs](https://help.sap.com/docs/r/f48e822d6d484fa5ade7dda78b64d9f5/Cloud/en-US/e6b90a5575f8401bb8469904a159788e.html) · [Audit Log Retrieval API no Cloud Foundry](https://help.sap.com/viewer/65de2977205c403bbc107264b8eccf4b/Cloud/en-US/30ece35bac024ca69de8b16bff79c413.html)
* 7: [SAP Data Privacy Integration](https://help.sap.com/docs/DATA_PRIVACY_INTEGRATION/c829f95e3a3a43ddb958782fb3bf61e2?locale=en-US&state=PRODUCTION&version=Cloud) · [Personal Data Manager: Security](https://help.sap.com/docs/personal-data-manager/development/security)
* 8: [What Is SAP Private Link Service?](https://help.sap.com/docs/private-link/private-link1/what-is-sap-private-link-service?locale=en-US) · [Cloud Connector](https://help.sap.com/docs/connectivity/sap-btp-connectivity-cf/cloud-connector)
* 9: [SAP Cloud Identity Access Governance](https://help.sap.com/docs/r/p/SAP_CLOUD_IDENTITY_ACCESS_GOVERNANCE)
* 10: [Secure Login Service: Feature Scope (PDF)](https://help.sap.com/doc/fc1ebf36cba74aee94cbc034320ba97c/Cloud/en-US/55a9b1434383479292cb724441055cbc.pdf) · [SAP GUI MFA com Secure Login Service e Entra ID (SAP Community)](https://blogs.sap.com/t5/technology-blogs-by-members/sap-gui-mfa-with-sap-secure-login-service-and-microsoft-entra-id/ba-p/13605383)
* 11: [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/) · [Model Context Protocol, seção Authorization](https://modelcontextprotocol.io)
* 12: [Security Best Practices for Application Frontend Service](https://help.sap.com/docs/application-frontend-service/application-frontend-service/security-best-practices-for-application-frontend-service?locale=en-US&version=Cloud)
* 13: [Terraform Provider for SAP BTP](https://registry.terraform.io/providers/SAP/btp/latest)
