## 10 Risky Clauses and Proposed Alternative Language

### 1. **Overly Broad Limitation of Liability Clause**

**Risky Language:**
*"Provider's total liability to Customer for any and all claims arising from this Agreement shall not exceed the fees paid by Customer in the twelve (12) months preceding the claim, regardless of the form of action."*

**Proposed Alternative:**
*"Provider's total liability to Customer for any claims arising from this Agreement shall not exceed the greater of (i) fees paid by Customer in the twelve (12) months preceding the claim or (ii) $500,000, except for claims arising from: (a) Provider's gross negligence or willful misconduct, (b) data breaches caused by Provider's failure to maintain agreed security standards, (c) intellectual property infringement, (d) breach of confidentiality obligations, (e) intentional suspension of services, or (f) violation of data protection laws, which shall be subject to Provider's insurance coverage limits of no less than $5,000,000."*

**Justification:** 

Standard limitations create traps for customers, and exclusions should apply equally to indirect damages and liability caps. Customers often push for uncapped liability for severe issues like data breaches and IP violations to ensure full protection when major incidents occur. A meaningful base cap addresses the business reality that low annual fees may not reflect actual damages, while carve-outs for critical violations ensure provider accountability for fundamental security and legal breaches. The insurance-based super cap provides realistic protection without creating unlimited exposure that could bankrupt the provider. 

GDPR Article 28(3)(d) requires processor contracts to address subprocessor engagement with controller authorization and processors remain liable for subprocessor compliance failures
.

CCPA penalties include annual cybersecurity audits for businesses processing personal information at significant risk levels
. 
Primary position: unlimited data breach liability. Fallback: 24-month fee cap with $5M insurance minimum. Vendor concern: unlimited exposure could bankrupt smaller providers. Compromise: insurance-backed liability with annual coverage review.

### 2. **Immediate Service Suspension Without Notice**

**Risky Language:**
*"Provider may immediately suspend Customer's access to the Services without notice if Customer: (a) fails to pay any amount when due, (b) violates any Acceptable Use Policy, or (c) takes any action that may harm Provider's systems or other customers."*

**Proposed Alternative:**
*"Provider may suspend Customer's access to the Services only after: (i) providing written notice specifying the violation with reasonable detail, (ii) allowing Customer ten (10) business days to cure any payment defaults or fifteen (15) business days to cure other material violations (except where immediate suspension is necessary to prevent imminent security threats or illegal activity), and (iii) confirming that Customer has failed to cure within the specified period. Provider must restore Services immediately upon cure. Emergency suspensions for genuine security threats require immediate notice and must be limited to the minimum scope necessary."*

**Justification:**

When services are critical to business operations, suspension can have disastrous consequences regardless of duration. Suspension may be a significant concern especially if the SaaS solution is critical to client business operations or their end customers. Prudent customers try to limit suspension solely to material violations that threaten cloud service security. Business continuity requires due process protections, particularly for payment disputes which often involve administrative errors rather than intentional default. The cure period recognizes that many violations are inadvertent and correctable. For customer service operations, system downtime exceeding 2 hours results in SLA breaches with end customers. For financial reporting, month-end processing delays could trigger SEC filing violations. Service suspension could result in $50,000 daily revenue loss for e-commerce customers or 75% productivity reduction for SaaS-dependent operations.

### 3. **Inadequate Security Audit Rights and Compliance Requirements**

**Risky Language:**
*"Provider will implement reasonable security measures. Customer may review Provider's annual SOC 2 report upon request. Provider has no obligation to permit Customer audits of security controls or compliance verification."*

**Proposed Alternative:**
*"Provider shall maintain 
SOC 2 Type II compliance with annual audits based on Trust Services Criteria covering security, availability, processing integrity, confidentiality, and privacy
, 
ISO 27001 certification for healthcare organizations handling protected health information (PHI) in compliance with HIPAA regulations
, and 
PCI-DSS compliance for any organization that processes, stores, or transmits credit card information with technical and operational requirements designed to protect cardholder data
. 
For government customers, Provider must achieve and maintain FedRAMP authorization at appropriate impact levels, with agencies required to assume that the security assessment in the authorization package is sufficient for granting their own authorization to operate at that same or lower impact level
. 
Any cloud service provider that creates, collects, stores, processes, or transmits federal data on the cloud must obtain FedRAMP authorization
. Customer shall have the right to conduct annual security audits of Provider's facilities and systems, including all subcontractors handling Customer Data, with 
thirty (30) days advance notice, provided Customer may not conduct more than one security audit during any twelve (12) month period
. 
Security audits shall be conducted annually during the term of this Agreement, encompassing data protection measures, access controls, encryption, incident response procedures, and compliance with relevant cybersecurity standards
. Provider must provide quarterly compliance reports and allow Customer to review SOC 2 reports within 30 days of issuance. Annual third-party penetration testing results must be shared with Customer. 
Customer must conduct annual or more frequent security audits to ensure financial information obtained from consumers is protected by security practices including adequate levels of physical security, personnel and access controls, and network security
."*

**Justification:**


SOC 2 compliance processes are flexible, with businesses undergoing annual audits based on relevant Trust Services Criteria, with audits unique to each organization's specific security requirements
. 
Organizations in the healthcare sector handling protected health information can align their SOC 2 controls with HIPAA requirements to demonstrate strong commitment to data protection, though SOC 2 compliance complements but does not substitute for full HIPAA compliance assessment
. 
FedRAMP is required for any cloud service provider who has developed a cloud service offering designed to work with a federal agency, and whenever a federal agency shares sensitive federal data on the cloud, it must adhere to FedRAMP standards
. Without adequate audit rights, customers cannot verify security compliance or assess actual risk exposure. 
Security audit clauses grant parties the right to review and assess security measures through scheduled or ad hoc inspections of systems, policies, and procedures to ensure compliance with agreed-upon security standards, helping to mitigate risks related to data breaches or non-compliance
. Sector-specific compliance requirements create mandatory audit obligations that standard "reasonable security" language fails to address.

### 4. **Unlimited Vendor Termination for Convenience**

**Risky Language:**
*"Provider may terminate this Agreement for any reason with thirty (30) days' written notice to Customer."*

**Proposed Alternative:**
*"Provider may terminate this Agreement for convenience only: (i) after the second anniversary of the Effective Date, (ii) with ninety (90) days' written notice, and (iii) subject to Provider's obligation to assist with data migration and provide transition services for an additional thirty (30) days at no additional cost. Customer may terminate for convenience at any time with sixty (60) days' notice. Any termination for convenience by Provider requires refund of prepaid fees for unused services."*

**Justification:**

Providers often include termination for convenience rights in their form agreements, which customers should evaluate for acceptability. Customers need basic transition assistance requirements that obligate providers to assist in transitioning services in-house or to another third party. Asymmetric termination rights create vendor lock-in and undermine customer bargaining power. The two-year restriction allows providers to recover implementation costs while preventing arbitrary termination during critical dependency periods. Mandatory transition assistance and refunds protect customer investments and business continuity. Implementation requires detailed project phases including legal review (60-90 days), technical requirement validation, and stakeholder coordination between IT, procurement, and business units. Rollback procedures must account for potential service interruptions during security control upgrades and data migration activities. Change management processes should include end-user training and communication plans to minimize operational disruption during provider transitions. For contracts under $100K annually, accept 12-month liability caps; for strategic partnerships over $500K, pursue unlimited liability for critical violations.

### 5. **Vague Data Ownership and Usage Rights**

**Risky Language:**
*"Customer grants Provider a perpetual, worldwide license to use Customer Data to improve Services, develop new features, and create aggregated analytics for business purposes."*

**Proposed Alternative:**
*"Customer retains all right, title, and interest in Customer Data. Customer grants Provider solely a limited, non-exclusive license to access and use Customer Data solely as necessary to provide the Services to Customer during the Term. 

Provider shall comply with GDPR Article 28 processor obligations including maintaining records of processing activities, implementing appropriate technical and organizational measures pursuant to Article 32, and ensuring staff confidentiality obligations
. 

Provider may engage subprocessors only with Customer's prior written consent and must provide 30 days advance notice of new subprocessors with Customer's right to object and require alternative processing arrangements
. Provider may not use Customer Data for any other purpose without Customer's prior written consent. Upon termination, Provider must securely delete all Customer Data within thirty (30) days, except as required by law. Provider must notify Customer within 24 hours of any security incident affecting Customer Data and provide forensic cooperation including log access and technical assistance. Any use of de-identified or aggregated data requires: (i) true anonymization that prevents re-identification, (ii) Customer's express written consent, and (iii) contractual prohibition on any attempt to re-identify Customer or its users. Data retention periods must align with specific business purposes, with automatic deletion after 90 days post-termination unless explicit legal hold requirements apply. Data minimization principles require Provider to collect and process only data elements essential for service delivery, with quarterly assessments to eliminate unnecessary data collection practices."*

**Justification:**

A robust SaaS agreement will unequivocally state that the customer retains all right, title, and interest in customer data, which is non-negotiable for the customer. If data ownership isn't crystal clear, that's a major red flag that could lead to significant complications. The biggest risk in SaaS provider use of de-identified customer data is re-identification, requiring understanding of both use case and de-identification processes. Clear data ownership prevents vendor overreach while specific limitations on derivative uses protect against unauthorized commercialization of customer information. 
GDPR Article 28(3)(d) requires processor contracts to address subprocessor engagement with controller authorization and processors remain liable for subprocessor compliance failures
.

### 6. **Weak Service Level Agreements**

**Risky Language:**
*"Provider will use commercially reasonable efforts to maintain Service availability. Customer's sole remedy for Service unavailability is service credits equal to the pro-rated fees for the period of unavailability."*

**Proposed Alternative:**
*"Provider guarantees: (i) 99.9% monthly uptime calculated as (Total Minutes in Month - Unscheduled Downtime Minutes) / Total Minutes in Month, measured from Customer's primary access point with 5-minute polling intervals (excluding planned maintenance during designated windows), with additional geographic measurement points for global customers and network latency thresholds of <200ms for 95% of requests, (ii) initial response to Priority 1 issues within two (2) hours, (iii) resolution of Priority 1 issues within eight (8) hours, and (iv) monthly security patching. Remedies include: (a) service credits escalating by severity - Priority 1 outages: 25% monthly fees per hour; Priority 2 outages: 10% monthly fees per 4-hour period; Priority 3 outages: 5% monthly fees per day, (b) termination rights if uptime falls below 99% in any calendar month or 99.5% over any consecutive three-month period, (c) reimbursement of reasonable third-party costs incurred due to Provider's SLA breaches, (d) Customer may engage third-party services at Provider's expense during outages exceeding 4 hours, with Provider liable for reasonable mitigation costs up to 200% of monthly fees, and (e) mandatory improvement plans with 30-day implementation timelines following repeated SLA failures. Service credits do not limit other available remedies. SLA remedies should include automatic failover requirements for mission-critical applications, mandatory disaster recovery testing with customer participation, and progressive enforcement steps including mandatory improvement plans before termination thresholds."*

**Justification:**

Form agreements from providers may not include service level commitments, and without basic performance standards, customers have limited ability to claim breach and terminate if performance falls below expectations. Customers should be mindful of "sole and exclusive" remedy language that limits remedies to invoice credits in SLA violations. Service levels establish minimum performance obligations and access degree, but many providers don't offer meaningful SLAs. Specific uptime commitments with escalating penalties create proper incentives for reliability, while termination rights provide ultimate protection against persistent failures. Industry standard liability caps range from 12-24 months fees, with technology companies typically accepting unlimited liability for IP infringement. Uptime Guarantees: 99.5% is common, but 99.9% is often seen among leading providers, allowing for roughly 43 minutes of downtime each month.

### 7. **Inadequate Data Portability and Exit Rights**

**Risky Language:**
*"Upon termination, Customer may export its data for thirty (30) days in Provider's standard format, subject to payment of all outstanding fees."*

**Proposed Alternative:**
*"Customer has unconditional rights to export all Customer Data in machine-readable formats (including CSV, JSON, XML, and API access) throughout the Term and for ninety (90) days after termination or expiration, regardless of reason for termination including non-payment. Provider must provide reasonable assistance with data migration at no additional charge for the first forty (40) hours and technical documentation and sample code for data migration tools, including field mapping guides and transformation scripts for common target systems. Customer Data includes all content, configurations, customizations, reports, and metadata. Provider must provide third-party audited certification of data deletion with forensic verification that data cannot be recovered from all systems including backups and disaster recovery sites, with regulatory compliance documentation for industries subject to specific retention requirements. Customer may request one 30-day extension for complex data migrations involving more than 100GB of data or custom integrations, subject to Provider's reasonable approval. Real-time data synchronization capabilities must be available during transition periods to ensure data integrity validation throughout the migration process."*

**Justification:**

Good SaaS contracts clearly define rights to export data in standard formats without penalties or delays, and vendors should allow unconditional data export even for non-payment terminations. Upon SaaS contract conclusion, customers need ability to retrieve data and transition smoothly to another provider. Without strong exit rights, "ownership" is meaningless and customers are trapped. Unconditional export rights prevent vendor lock-in tactics, while extended timeframes and technical assistance ensure realistic data recovery. Payment-independent access prevents vendors from holding data hostage during disputes. Automatic extensions should apply for customers with regulatory retention requirements or complex multi-system integrations that require additional validation and testing phases.

### 8. **Broad Indemnification Exclusions**

**Risky Language:**
*"Provider has no obligation to indemnify Customer for any claims arising from: (a) Customer's use of Services in combination with other software, (b) modifications to Services, (c) use of Services contrary to documentation, or (d) any third-party content or services."*

**Proposed Alternative:**
*"Provider shall defend, indemnify, and hold harmless Customer against any third-party claims alleging that the Services, when used as documented and licensed hereunder, infringe any patent, copyright, or trade secret. Indemnification includes Customer's use of documented APIs and authorized third-party integrations specifically approved by Provider in writing, including coverage for open source components and third-party libraries integrated into the service platform. Provider's indemnification obligations do not apply only to claims directly resulting from: (a) Customer's unauthorized modifications to the Services themselves (not configurations), (b) Customer's use of Services in violation of written Provider instructions after specific written notice of infringement risk, or (c) Customer's combination of Services with technology that Provider specifically identifies as incompatible. 
Provider shall indemnify Customer for regulatory fines and penalties arising from Provider's non-compliance with GDPR, CCPA, HIPAA, PCI-DSS, SOX for financial services, FedRAMP for government customers, or other applicable data protection laws. Provider shall control defense of indemnified claims but must consult with Customer on strategy and obtain Customer's consent for any settlement that admits liability, requires Customer action, or affects Customer's ongoing operations. Customer shall have co-counsel rights for matters affecting core business operations, with right to separate counsel at Provider's expense when vendor and customer interests materially diverge in defense strategy."*

**Justification:**

SaaS buyers face risk that solutions may infringe third-party IP, and it's extremely important agreements include third-party IP indemnification where SaaS vendors take liability for infringement claims against buyers. Overly broad exclusions leave customers exposed to risks they cannot assess or control. Standard use cases, including reasonable integrations and configurations, should receive indemnification protection. The narrowed exclusions focus on genuine customer-caused risks rather than normal business usage, while mutual provisions ensure balanced risk allocation. 
The PCI DSS defines security requirements to protect environments where payment account data is stored, processed, or transmitted, with all entities involved in payment card processing subject to PCI DSS standards
. Sector-specific regulations including SOX for financial reporting and FedRAMP for government customers require comprehensive regulatory indemnification coverage.

### 9. **Unilateral Contract Modification Rights**

**Risky Language:**
*"Provider may modify this Agreement at any time by posting updated terms on its website. Continued use of Services constitutes acceptance of modified terms."*

**Proposed Alternative:**
*"Provider may not modify this Agreement without Customer's written consent, except for: (a) changes required by law, or (b) updates to Acceptable Use Policies that do not materially expand prohibited activities. Any such permitted changes require ninety (90) days' advance written notice and specific identification of changes. Material adverse changes give Customer the right to terminate this Agreement without penalty with thirty (30) days' notice. Continued use does not constitute acceptance of material changes without express written consent. Detailed service feature definitions must include change control procedures requiring written approval for scope modifications and protection against unilateral service changes that could trigger additional fees. Annual price increase cap of 3% or CPI, whichever is lower, to prevent unlimited pricing discretion that could undermine budget predictability. All fees must be clearly categorized as: (i) base subscription fees, (ii) implementation/setup fees, (iii) usage-based fees with monthly caps, (iv) professional services fees, and (v) third-party pass-through costs with markup limitations not exceeding 15%. Billing shall commence only upon successful completion of user acceptance testing and full service availability, not contract signature date."*

**Justification:**

Contracts vague on critical points including terms of service allow providers to announce unfavorable changes, altering data usage rights and introducing additional fees for relied-upon features. Allowing SaaS vendors to unilaterally change terms without notice may be challenged legally or reduce trust. Unilateral modification rights fundamentally alter the contractual bargain and create uncertainty. The proposed language preserves necessary flexibility for legal compliance while protecting customers from arbitrary changes that could undermine their business models or increase costs. Enhanced change control procedures prevent scope creep charges and ensure transparency in service modifications that could impact customer operations.

### 10. **Inadequate Security Accountability and Breach Response**

**Risky Language:**
*"Provider will implement reasonable security measures and notify Customer of security incidents within a reasonable time. Provider's liability for security breaches is limited to the general liability cap."*

**Proposed Alternative:**
*"Provider shall implement and maintain security controls meeting or exceeding 
SOC 2 Type II standards with annual audits evaluating controls operating over a period of time (usually 6+ months)
, 
ISO 27001:2022 standards covering the five Trust Services Criteria of security, availability, processing integrity, confidentiality, and privacy
, including encryption at rest and in transit, multi-factor authentication, and regular penetration testing. 
Provider must maintain ongoing confidentiality, integrity, availability, and resilience of processing systems and conduct regular testing, assessing and evaluating the effectiveness of technical and organisational measures
. 

For payment processing customers, Provider must maintain PCI-DSS compliance with annual assessments and quarterly vulnerability scans, as all entities that store, process, or transmit cardholder data and could impact the security of the cardholder data environment are subject to PCI DSS standards
. 

For government customers, Provider must achieve and maintain FedRAMP authorization at appropriate impact levels, with agencies required to assume that the security assessment in the authorization package is sufficient for granting their own authorization to operate at that same or lower impact level
. For healthcare customers, audit rights must include HIPAA compliance verification with annual assessments of PHI handling procedures. Customer shall have immediate audit rights following security incidents, with annual SOC 2 Type II certification, quarterly vulnerability assessments with specific remediation timelines for critical findings. Provider must notify Customer of any actual or suspected security incidents affecting Customer Data within twenty-four (24) hours of discovery, provide detailed written reports within seventy-two (72) hours, cooperate fully with Customer's incident response activities, preserve all evidence, provide root cause analysis within 10 business days, and implement remediation measures approved by Customer. Security breach includes: (i) unauthorized access to Customer Data, (ii) failure to maintain required encryption standards, (iii) missed security patch installation beyond 30 days, (iv) failed penetration testing remediation, (v) SOC 2 control deficiencies, and (vi) insider threat incidents and third-party vendor security failures. Provider must cure security violations within 48 hours for critical issues, and repeated failures trigger termination rights. Security breaches caused by Provider's failure to maintain agreed security standards are subject to graduated liability structure: Minor security incidents (affecting <1000 records): standard liability cap. Major breaches (>1000 records or sensitive data): unlimited liability. Systemic failures: unlimited liability plus regulatory penalty coverage including 
GDPR fines up to 4% of annual revenue and CCPA penalties
, requiring minimum $10M coverage for enterprise customers."*

**Justification:**

Weak security and breach provisions can leave customers vulnerable and liable for expensive damages. 
GDPR Article 32 requires appropriate technical and organizational measures ensuring security appropriate to risk
. 
ISO/IEC 27001 is the world's best-known standard for information security management systems, providing companies guidance for establishing, implementing, maintaining and continually improving information security management systems that preserve confidentiality, integrity and availability of information through risk management processes
. Enhanced liability requirements may increase service costs by 10-15% but provide $2M+ protection value for data breach scenarios. Given constant massive data security breaches from various causes, SaaS vendors should be expected to handle tasks that reduce data breach risk. Specific security standards create enforceable obligations, while rapid notification enables effective incident response. Enhanced liability for security failures ensures providers internalize the true costs of data protection failures.

Each of these redlined clauses addresses fundamental imbalances in standard SaaS agreements that favor vendors at customers' expense. The proposed alternatives create more balanced risk allocation while maintaining commercial viability for both parties. Establish consistent risk thresholds across all areas - unlimited liability for intentional breaches, 24-month fee caps for negligent failures, and insurance-backed coverage for operational risks. For contracts under $50K annually, accept higher liability caps with insurance backing. For mission-critical applications, require unlimited liability for security failures. For non-regulated industries, focus on business continuity over compliance requirements. Risk tolerance calibration requires adjusting positions based on contract value, business criticality, and vendor size, with more moderate approaches for lower-risk scenarios and smaller vendors while maintaining substantive legal protections essential for effective contract negotiation.