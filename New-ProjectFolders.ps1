# New-ProjectFolders.ps1
# Prompts for a parent folder name and creates project subfolders

$parentName = Read-Host "Enter the project folder name"

if ([string]::IsNullOrWhiteSpace($parentName)) {
    Write-Host "No folder name provided. Exiting." -ForegroundColor Red
    exit
}

$basePath = "C:\Users\dpaine\OneDrive - Anduril 365 Gov\Documents\Ekahau AI Pro\Projects"
$parentPath = Join-Path -Path $basePath -ChildPath $parentName

if (Test-Path $parentPath) {
    Write-Host "Folder '$parentName' already exists at: $parentPath" -ForegroundColor Yellow
    exit
}

$subfolders = @("floorplans", "images", "reports")

New-Item -Path $parentPath -ItemType Directory | Out-Null
foreach ($folder in $subfolders) {
    New-Item -Path (Join-Path $parentPath $folder) -ItemType Directory | Out-Null
}

Write-Host "Created project folder '$parentName' with subfolders: $($subfolders -join ', ')" -ForegroundColor Green
