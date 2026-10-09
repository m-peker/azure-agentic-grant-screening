using 'main.bicep'

// Set before deploying:  export DEVELOPER_PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
param developerPrincipalId = readEnvironmentVariable('DEVELOPER_PRINCIPAL_ID')
param prefix = 'grant'
