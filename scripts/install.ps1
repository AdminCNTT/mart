# Set color theme
$Theme = @{
    Primary   = 'Cyan'
    Success   = 'Green'
    Warning   = 'Yellow'
    Error     = 'Red'
    Info      = 'White'
}

# ASCII Logo
$Logo = @"
   ██████╗  ██████╗ ██████╗ ███╗   ███╗ █████╗ ██████╗ ████████╗
  ██╔═══██╗██╔═══██╗██╔══██╗████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝
  ██║   ██║██║   ██║██████╔╝██╔████╔██║███████║██████╔╝   ██║   
  ██║   ██║██║   ██║██╔══██╗██║╚██╔╝██║██╔══██║██╔══██╗   ██║   
  ╚██████╔╝╚██████╔╝██║  ██║██║ ╚═╝ ██║██║  ██║██║  ██║   ██║   
   ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
"@

# Beautiful Output Function
function Write-Styled {
    param (
        [string]$Message,
        [string]$Color = $Theme.Info,
        [string]$Prefix = "",
        [switch]$NoNewline
    )
    $symbol = switch ($Color) {
        $Theme.Success { "[OK]" }
        $Theme.Error   { "[X]" }
        $Theme.Warning { "[!]" }
        default        { "[*]" }
    }
    
    $output = if ($Prefix) { "$symbol $Prefix :: $Message" } else { "$symbol $Message" }
    if ($NoNewline) {
        Write-Host $output -ForegroundColor $Color -NoNewline
    } else {
        Write-Host $output -ForegroundColor $Color
    }
}

# Check if Python is installed
function Test-PythonInstalled {
    try {
        $pythonVersion = python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            # Extract version number
            if ($pythonVersion -match "Python (\d+)\.(\d+)") {
                $major = [int]$matches[1]
                $minor = [int]$matches[2]
                if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 8)) {
                    Write-Styled "Python version $pythonVersion is too old. Need Python 3.8+" -Color $Theme.Warning -Prefix "Python"
                    return $false
                }
            }
            Write-Styled "Python found: $pythonVersion" -Color $Theme.Success -Prefix "Python"
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

# Install Python if not found
function Install-Python {
    Write-Styled "Python not found. Installing Python..." -Color $Theme.Warning -Prefix "Python"
    
    try {
        # Download Python installer
        $pythonUrl = "https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe"
        $installerPath = "$env:TEMP\python-installer.exe"
        
        Write-Styled "Downloading Python installer..." -Color $Theme.Primary -Prefix "Download"
        Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -UseBasicParsing
        
        Write-Styled "Installing Python (this may take a few minutes)..." -Color $Theme.Primary -Prefix "Install"
        Write-Styled "Please wait, installation is running in background..." -Color $Theme.Info -Prefix "Wait"
        $process = Start-Process -FilePath $installerPath -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -Wait -PassThru
        
        if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
            throw "Python installer exited with code $($process.ExitCode)"
        }
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        # Verify installation
        Start-Sleep -Seconds 3
        if (Test-PythonInstalled) {
            Write-Styled "Python installed successfully!" -Color $Theme.Success -Prefix "Success"
            return $true
        } else {
            throw "Python installation verification failed"
        }
    } catch {
        Write-Styled "Failed to install Python: $($_.Exception.Message)" -Color $Theme.Error -Prefix "Error"
        Write-Styled "Please install Python manually from https://www.python.org/downloads/" -Color $Theme.Warning -Prefix "Manual"
        return $false
    }
}

# Clone or download repository
function Get-Repository {
    param (
        [string]$RepoUrl,
        [string]$InstallPath
    )
    
    if (Test-Path $InstallPath) {
        Write-Styled "Directory already exists: $InstallPath" -Color $Theme.Warning -Prefix "Found"
        $response = Read-Host "Do you want to update it? (Y/N)"
        if ($response -eq "Y" -or $response -eq "y") {
            Remove-Item -Path $InstallPath -Recurse -Force
        } else {
            Write-Styled "Using existing directory" -Color $Theme.Info -Prefix "Info"
            return $true
        }
    }
    
    Write-Styled "Downloading repository..." -Color $Theme.Primary -Prefix "Download"
    
    try {
        # Check if git is available
        $gitAvailable = $false
        try {
            git --version | Out-Null
            $gitAvailable = $true
        } catch {
            $gitAvailable = $false
        }
        
        if ($gitAvailable) {
            Write-Styled "Using Git to clone repository..." -Color $Theme.Info -Prefix "Git"
            git clone $RepoUrl $InstallPath
            if ($LASTEXITCODE -eq 0) {
                Write-Styled "Repository cloned successfully!" -Color $Theme.Success -Prefix "Success"
                return $true
            }
        }
        
        # Fallback: Download as ZIP
        Write-Styled "Git not available, downloading as ZIP..." -Color $Theme.Info -Prefix "Download"
        
        # Parse GitHub URL to get user/repo
        if ($RepoUrl -match "github\.com[:/]([^/]+)/([^/]+)") {
            $githubUser = $matches[1]
            $repoName = $matches[2] -replace "\.git$", ""
            
            # Try main branch first, then master
            $zipUrl = "https://github.com/$githubUser/$repoName/archive/refs/heads/main.zip"
            $zipPath = "$env:TEMP\repo.zip"
            
            try {
                Write-Styled "Trying main branch..." -Color $Theme.Info -Prefix "Branch"
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -ErrorAction Stop
            } catch {
                Write-Styled "Main branch not found, trying master..." -Color $Theme.Warning -Prefix "Branch"
                $zipUrl = "https://github.com/$githubUser/$repoName/archive/refs/heads/master.zip"
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
            }
        } else {
            throw "Invalid GitHub URL format. Expected: https://github.com/user/repo.git"
        }
        
        # Extract ZIP
        Write-Styled "Extracting files..." -Color $Theme.Primary -Prefix "Extract"
        Expand-Archive -Path $zipPath -DestinationPath $InstallPath -Force
        Remove-Item $zipPath
        
        # Move files from subdirectory to main directory
        $subDirs = Get-ChildItem -Path $InstallPath -Directory
        if ($subDirs.Count -eq 1) {
            $subDir = $subDirs[0].FullName
            Get-ChildItem -Path $subDir | Move-Item -Destination $InstallPath -Force
            Remove-Item $subDir
        }
        
        Write-Styled "Repository downloaded successfully!" -Color $Theme.Success -Prefix "Success"
        return $true
        
    } catch {
        Write-Styled "Failed to download repository: $($_.Exception.Message)" -Color $Theme.Error -Prefix "Error"
        return $false
    }
}

# Clean requirements.txt (remove invalid lines)
function Remove-InvalidRequirements {
    param (
        [string]$RequirementsPath
    )
    
    $content = Get-Content $RequirementsPath
    $cleanedContent = @()
    
    foreach ($line in $content) {
        $trimmed = $line.Trim()
        # Skip empty lines, comments, and command lines
        if ($trimmed -and 
            -not $trimmed.StartsWith("#") -and 
            -not $trimmed.StartsWith("pip install") -and
            -not $trimmed.StartsWith("python ") -and
            ($trimmed -match "^[a-zA-Z0-9_-]+" -or $trimmed -match "^[a-zA-Z0-9_-]+.*==|>=|<=|>|<|~=")) {
            $cleanedContent += $trimmed
        }
    }
    
    # Create backup and write cleaned version
    $backupPath = "$RequirementsPath.backup"
    Copy-Item $RequirementsPath $backupPath -Force
    $cleanedContent | Set-Content $RequirementsPath
    
    if ($cleanedContent.Count -lt $content.Count) {
        Write-Styled "Cleaned requirements.txt (removed $($content.Count - $cleanedContent.Count) invalid lines)" -Color $Theme.Warning -Prefix "Clean"
    }
}

# Install Python dependencies
function Install-Dependencies {
    param (
        [string]$ProjectPath
    )
    
    $requirementsPath = Join-Path $ProjectPath "requirements.txt"
    
    if (-not (Test-Path $requirementsPath)) {
        Write-Styled "requirements.txt not found!" -Color $Theme.Warning -Prefix "Warning"
        return $false
    }
    
    Write-Styled "Installing Python dependencies..." -Color $Theme.Primary -Prefix "Install"
    
    try {
        # Clean requirements.txt first
        Remove-InvalidRequirements -RequirementsPath $requirementsPath
        
        # Upgrade pip first
        Write-Styled "Upgrading pip..." -Color $Theme.Info -Prefix "Pip"
        python -m pip install --upgrade pip --quiet 2>&1 | Out-Null
        
        # Install torch separately first (large package, may need special handling)
        Write-Styled "Installing PyTorch (this may take a while)..." -Color $Theme.Info -Prefix "PyTorch"
        python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu 2>&1 | Out-Null
        
        # Install other requirements
        Write-Styled "Installing other packages from requirements.txt..." -Color $Theme.Info -Prefix "Packages"
        python -m pip install -r $requirementsPath 2>&1 | Out-Null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Styled "All dependencies installed successfully!" -Color $Theme.Success -Prefix "Success"
            return $true
        } else {
            # Try without torch (might already be installed)
            Write-Styled "Retrying installation..." -Color $Theme.Warning -Prefix "Retry"
            python -m pip install -r $requirementsPath --ignore-installed 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Styled "Dependencies installed (with warnings)" -Color $Theme.Success -Prefix "Success"
                return $true
            }
            throw "pip install failed"
        }
    } catch {
        Write-Styled "Failed to install dependencies: $($_.Exception.Message)" -Color $Theme.Error -Prefix "Error"
        Write-Styled "You may need to install manually: python -m pip install -r requirements.txt" -Color $Theme.Warning -Prefix "Manual"
        return $false
    }
}

# Main installation function
function Install-Project {
    param (
        [string]$RepoUrl = "https://github.com/YOUR_USERNAME/YOUR_REPO.git",
        [string]$InstallPath = "$env:USERPROFILE\POPMART2",
        [switch]$RunAfterInstall
    )
    
    # Show Logo
    Write-Host $Logo -ForegroundColor $Theme.Primary
    Write-Host "`nAuto Installation Script`n" -ForegroundColor $Theme.Info
    
    # Set TLS 1.2
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    
    try {
        # Step 1: Check/Install Python
        Write-Styled "Step 1: Checking Python installation..." -Color $Theme.Primary -Prefix "Step 1"
        if (-not (Test-PythonInstalled)) {
            if (-not (Install-Python)) {
                throw "Python installation failed"
            }
        }
        
        # Step 2: Download Repository
        Write-Styled "Step 2: Downloading repository..." -Color $Theme.Primary -Prefix "Step 2"
        if (-not (Get-Repository -RepoUrl $RepoUrl -InstallPath $InstallPath)) {
            throw "Repository download failed"
        }
        
        # Step 3: Install Dependencies
        Write-Styled "Step 3: Installing dependencies..." -Color $Theme.Primary -Prefix "Step 3"
        Write-Styled "This may take several minutes, especially for PyTorch..." -Color $Theme.Warning -Prefix "Note"
        if (-not (Install-Dependencies -ProjectPath $InstallPath)) {
            Write-Styled "Warning: Some dependencies may have failed to install" -Color $Theme.Warning -Prefix "Warning"
            Write-Styled "You can try installing manually later" -Color $Theme.Info -Prefix "Info"
        }
        
        Write-Styled "`n✅ Installation completed successfully!" -Color $Theme.Success -Prefix "Complete"
        Write-Styled "Project location: $InstallPath" -Color $Theme.Info -Prefix "Location"
        
        # Verify main files exist
        $mainFile = Join-Path $InstallPath "auto_v2.py"
        if (Test-Path $mainFile) {
            Write-Styled "Main script found: auto_v2.py" -Color $Theme.Success -Prefix "Verify"
        } else {
            Write-Styled "Warning: auto_v2.py not found in project" -Color $Theme.Warning -Prefix "Verify"
        }
        
        # Step 4: Run project (optional)
        if ($RunAfterInstall) {
            Write-Styled "`nStep 4: Running project..." -Color $Theme.Primary -Prefix "Step 4"
            Set-Location $InstallPath
            Write-Styled "To run the project, use:" -Color $Theme.Info -Prefix "Run"
            Write-Host "  cd $InstallPath" -ForegroundColor $Theme.Info
            Write-Host "  python auto_v2.py --max-workers 10" -ForegroundColor $Theme.Info
        } else {
            Write-Styled "`nTo run the project:" -Color $Theme.Info -Prefix "Next"
            Write-Host "  cd $InstallPath" -ForegroundColor $Theme.Info
            Write-Host "  python auto_v2.py --max-workers 10" -ForegroundColor $Theme.Info
            Write-Host "`nOr with target time:" -ForegroundColor $Theme.Info
            Write-Host "  python auto_v2.py --max-workers 10 --target-time `"2025-11-12 13:30:00`"" -ForegroundColor $Theme.Info
        }
        
    } catch {
        Write-Styled "`n❌ Installation failed!" -Color $Theme.Error -Prefix "Error"
        Write-Styled $_.Exception.Message -Color $Theme.Error
        return $false
    }
    
    return $true
}

# Execute installation
try {
    # ⚠️ THAY ĐỔI URL NÀY THÀNH URL REPO CỦA BẠN
    $repoUrl = "https://github.com/YOUR_USERNAME/YOUR_REPO.git"
    
    # ⚠️ CÓ THỂ THAY ĐỔI ĐƯỜNG DẪN CÀI ĐẶT
    $installPath = "$env:USERPROFILE\POPMART2"
    
    Install-Project -RepoUrl $repoUrl -InstallPath $installPath
}
catch {
    Write-Styled "Fatal error: $($_.Exception.Message)" -Color $Theme.Error -Prefix "Fatal"
}
finally {
    Write-Host "`nPress any key to exit..." -ForegroundColor $Theme.Info
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}
