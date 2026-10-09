// Phase 0 infrastructure: Microsoft Foundry (account + project + model deployments)
// and the three free-tier (F0) Azure AI services used by stage A.
//
// Deploy:
//   az deployment group create -g rg-grant-screening-dev -f infra/main.bicep -p infra/main.bicepparam
//
// All services use Entra ID auth only (disableLocalAuth = true): no API keys exist.

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short prefix used in resource names.')
param prefix string = 'grant'

@description('Object ID of the developer who runs the code locally (az ad signed-in-user show --query id -o tsv).')
param developerPrincipalId string

@description('Chat model used by LLM stages and agents.')
param chatModel object = {
  name: 'gpt-5.4-mini'
  version: '2026-03-17'
  sku: 'GlobalStandard'
  capacity: 50 // thousands of tokens per minute
}

@description('Embedding model used by hybrid search.')
param embeddingModel object = {
  name: 'text-embedding-3-small'
  version: '1'
  sku: 'GlobalStandard'
  capacity: 50
}

var suffix = substring(uniqueString(resourceGroup().id), 0, 6)
var tags = {
  project: 'grant-screening'
  env: 'dev'
}

// Built-in role definition IDs
var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

// ---------------------------------------------------------------------------
// Microsoft Foundry: one account (the "resource") hosting one project.
// The account owns model deployments and quota; the project is the workspace
// where agents, threads, evaluations and connections live.
// ---------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' = {
  name: 'aif-${prefix}-${suffix}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${prefix}-${suffix}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' = {
  parent: foundry
  name: 'proj-${prefix}-screening'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Grant screening'
    description: 'Agentic grant proposal eligibility screening (learning project).'
  }
  // The account accepts one write at a time: serialize project after deployments
  // to avoid "RequestConflict: Another operation is in progress".
  dependsOn: [ embeddingDeployment ]
}

// Deployments on the same account must be created one at a time.
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: 'chat'
  sku: { name: chatModel.sku, capacity: chatModel.capacity }
  properties: {
    model: { format: 'OpenAI', name: chatModel.name, version: chatModel.version }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: 'embedding'
  sku: { name: embeddingModel.sku, capacity: embeddingModel.capacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingModel.name, version: embeddingModel.version }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [ chatDeployment ]
}

// ---------------------------------------------------------------------------
// Free-tier AI services for stage A (intake & shield)
// ---------------------------------------------------------------------------
var f0Services = [
  { key: 'docintel', kind: 'FormRecognizer', name: 'di-${prefix}-${suffix}' }  // A1 layout OCR
  { key: 'language', kind: 'TextAnalytics', name: 'lang-${prefix}-${suffix}' } // A3 PII
  { key: 'safety', kind: 'ContentSafety', name: 'cs-${prefix}-${suffix}' }     // A2 Prompt Shields
]

resource aiServices 'Microsoft.CognitiveServices/accounts@2026-07-01' = [for s in f0Services: {
  name: s.name
  location: location
  tags: tags
  kind: s.kind
  sku: { name: 'F0' }
  properties: {
    customSubDomainName: s.name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}]

// ---------------------------------------------------------------------------
// RBAC for the local developer (DefaultAzureCredential -> az login)
// ---------------------------------------------------------------------------
resource devFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, developerPrincipalId, roles.foundryUser)
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource devOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, developerPrincipalId, roles.cognitiveServicesOpenAIUser)
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
  }
}

resource devServiceUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (s, i) in f0Services: {
  scope: aiServices[i]
  name: guid(aiServices[i].id, developerPrincipalId, roles.cognitiveServicesUser)
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
  }
}]

// ---------------------------------------------------------------------------
// Phase 5: Azure AI Search, Free tier (no fixed cost; one per subscription).
// Entra ID for data plane; keys stay enabled only because the Free tier
// cannot use managed identity for outbound calls (we embed client-side).
// ---------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: 'srch-${prefix}-${suffix}'
  location: location
  tags: tags
  sku: { name: 'free' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    semanticSearch: 'free'
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
  }
}

var searchRoles = [
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // Search Service Contributor (create indexes)
]

resource devSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in searchRoles: {
  scope: search
  name: guid(search.id, developerPrincipalId, roleId)
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

// ---------------------------------------------------------------------------
// Phase 8: observability. Workspace-based Application Insights with a daily
// ingestion cap (cost safety) and Entra-only ingestion (no instrumentation key auth).
// ---------------------------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${prefix}-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: true
  }
}

resource devTelemetryPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appInsights
  name: guid(appInsights.id, developerPrincipalId, '3913510d-42f4-4e42-8a64-420c390055eb')
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb') // Monitoring Metrics Publisher
  }
}

// ---------------------------------------------------------------------------
// Phase 9: audit store, secrets, officer web app (all without fixed monthly cost)
// ---------------------------------------------------------------------------
@description('Deploy the officer web app (App Service F1, free tier).')
param deployWebApp bool = true

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-${prefix}-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [ { name: 'EnableServerless' } ]
    locations: [ { locationName: location, failoverPriority: 0 } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true // Entra ID only
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'screening'
  properties: { resource: { id: 'screening' } }
}

// results: one document per application (latest state shown to officers)
// decisions: officer actions waiting to be applied to paused workflows
// audit: immutable decision records
// submissions: uploaded proposals waiting for / under screening
resource cosmosContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in [ 'results', 'decisions', 'audit', 'submissions' ]: {
  parent: cosmosDb
  name: c
  properties: {
    resource: {
      id: c
      partitionKey: { paths: [ '/application_id' ], kind: 'Hash' }
    }
  }
}]

var cosmosDataContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource devCosmosData 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, developerPrincipalId, 'data-contributor')
  properties: { principalId: developerPrincipalId, roleDefinitionId: cosmosDataContributor, scope: cosmos.id }
}

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: 'kv-${prefix}-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource devVaultOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, developerPrincipalId, 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7') // Key Vault Secrets Officer
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = if (deployWebApp) {
  name: 'asp-${prefix}-${suffix}'
  location: location
  tags: tags
  sku: { name: 'F1', tier: 'Free' }
  kind: 'linux'
  properties: { reserved: true }
}

resource web 'Microsoft.Web/sites@2024-04-01' = if (deployWebApp) {
  name: 'app-${prefix}-${suffix}'
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'gunicorn -w 1 -k uvicorn.workers.UvicornWorker --timeout 120 app:app'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
        { name: 'STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
        // Easy Auth client secret via Key Vault reference. Declared here so that a Bicep
        // redeploy (which replaces all app settings) cannot silently break sign-in.
        { name: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET', value: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=easyauth-client-secret)' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
      ]
    }
  }
}

resource webCosmosData 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (deployWebApp) {
  parent: cosmos
  name: guid(cosmos.id, 'webapp', 'data-contributor')
  properties: { principalId: web!.identity.principalId, roleDefinitionId: cosmosDataContributor, scope: cosmos.id }
  dependsOn: [ devCosmosData ]
}

resource webVaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployWebApp) {
  scope: vault
  name: guid(vault.id, 'webapp', '4633458b-17de-408a-b874-0445c86b69e6')
  properties: {
    principalId: web!.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
  }
}

// ---------------------------------------------------------------------------
// Proposal documents: Blob Storage (pay per GB, no fixed cost).
// Shared-key access and public blobs are disabled: Entra ID only.
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${prefix}${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource proposalsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'proposals'
  properties: { publicAccess: 'None' }
}

resource devBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, developerPrincipalId, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
  }
}

// The officer UI uploads new proposals, so it needs write access to blobs.
resource webBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployWebApp) {
  scope: storage
  name: guid(storage.id, 'webapp', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  properties: {
    principalId: web!.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
  }
}

// ---------------------------------------------------------------------------
// Outputs -> copy into .env
// ---------------------------------------------------------------------------
output FOUNDRY_PROJECT_ENDPOINT string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output CHAT_DEPLOYMENT string = chatDeployment.name
output EMBEDDING_DEPLOYMENT string = embeddingDeployment.name
output DOCUMENT_INTELLIGENCE_ENDPOINT string = aiServices[0].properties.endpoint
output LANGUAGE_ENDPOINT string = aiServices[1].properties.endpoint
output CONTENT_SAFETY_ENDPOINT string = aiServices[2].properties.endpoint
output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString
output COSMOS_ENDPOINT string = cosmos.properties.documentEndpoint
output KEY_VAULT_NAME string = vault.name
output WEBAPP_NAME string = deployWebApp ? web.name : ''
output STORAGE_ACCOUNT_URL string = storage.properties.primaryEndpoints.blob
