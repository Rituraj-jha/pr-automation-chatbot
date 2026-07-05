Object Type	Account Association	Data Layer / Indentifier	Convention	Examples	Description (if any)	Reference Development Templates / Examples
(Use equivalent templates from the main branch for Production)	Eligible Tags
S3 Bucket	Lakehouse	Ent/Func Specific Source Buckets	[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[dp/src/scripts/eng-assets/ops]	dev-lh1-corp-fin-src
dev-lh1-agtr-src	For the lakehouse source buckets, the [OWNING_ENTITY] should be at level of Enterprise/Function and not beyond	
SRC_S3_Bucket_Example

 

Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup (in case of CORP)
Framework
map-migrated
UsageType
S3 Bucket	Lakehouse	Source System specific Buckets
(for sources not aligned to Ent/Func)	[AWS_ACCT_ABBR]-[SRC_SYS_NAME]-[dp/src/scripts/eng-assets/ops]	dev-lh1-sap-src	Per alignment with Governance no source resources will likely get ingested which aren't aligned to an Ent/Func.	Deprecated since this is not allowed with Minerva Governance guidance.	Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup (in case of CORP)
Source
Framework
map-migrated
UsageType
 
S3 Bucket	Compute	Ent/Func Subgroup Specific Data Product Buckets	[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[dp/src/scripts/eng-assets/ops]	dev-cmp1-wtg-dp
dev-cmp1-wtg-cdas-dp
dev-cmp2-gi-sust-dp	For compute account data product buckets, the expectation is to not have owning entity beyond subgroup levels.
Since S3 Buckets are universal, even Dev and Prod buckets may collide, hence lets include identifier here.	Products_S3_Bucket_Example	Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup
Framework
map-migrated
UsageType
 
S3 Bucket	Compute / Lakehouse	Owning entity specific scripts Buckets	[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[dp/src/scripts/eng-assets/ops]	dev-lh1-corp-fin-scripts
dev-cmp1-wtg-scripts
dev-cmp3-cbi-scripts
dev-cmp4-salt-scripts	If in Lakehouse account, the owning entity should be restricted to Enterprise/Function, while in Compute account it should be subgroup
Since S3 Buckets are universal, even Dev and Prod buckets may collide, hence lets include identifier here.	
Source_Scripts_Bucket_Example

 

Data_Product_Scripts_Bucket_Example

 

Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup
Framework
UsageType
 
S3 Bucket	Compute / Lakehouse	Owning entity specific logs and temp Data in Eng-asset buckets	[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[dp/src/scripts/eng-assets/ops]	dev-lh1-corp-fin-eng-assets
dev-cmp1-wtg-eng-assets
dev-cmp3-cbi-eng-assets
dev-cmp4-salt-eng-assets	If in Lakehouse account, the owning entity should be restricted to Enterprise/Function, while in Compute account it should be subgroup
Since S3 Buckets are universal, even Dev and Prod buckets may collide, hence lets include identifier here.	
Source_Eng_Assets_Bucket_Example

 

Compute_Eng_Assets_Bucket_Example

 

Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup
Framework
UsageType
 
S3 Bucket	Lakehouse/Compute	Owning entity specific operations Buckets	[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[dp/src/scripts/eng-assets/ops]	dev-lh1-corp-fin-ops
dev-lh1-dtd-miw-ops
dev-cmp1-dtd-miw-ops
dev-cmp4-salt-ops	Can likely be used for ad-hoc CSV dumps, explict reports and more.
Think of it like a futuristic safegaurding mechansim
If in Lakehouse account, the owning entity should be restricted to Enterprise/Function, while in Compute account it should be subgroup
Since S3 Buckets are universal, even Dev and Prod buckets may collide, hence lets include identifier here.	Not an immediate requirement but if you need this template, please reach out to MIW Team.	Region
CodePipeline
OwningEnterpriseFunction
OwningSubgroup
Framework
UsageType
 