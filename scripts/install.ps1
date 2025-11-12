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

# Show progress spinner
function Show-Spinner {
    param (
        [string]$Message,
        [scriptblock]$ScriptBlock
    )
    $spinner = @('|', '/', '-', '\')
    $job = Start-Job -ScriptBlock $ScriptBlock
    $i = 0
    while ($job.State -eq 'Running') {
        $spinnerChar = $spinner[$i % $spinner.Length]
        Write-Host "`r[$spinnerChar] $Message" -NoNewline -ForegroundColor $Theme.Primary
        Start-Sleep -Milliseconds 200
        $i++
    }
    Write-Host "`r" -NoNewline
    $result = Receive-Job $job
    Remove-Job $job
    return $result
}

# Install Python if not found
function Install-Python {
    Write-Styled "Python not found. Installing Python..." -Color $Theme.Warning -Prefix "Python"
    
    try {
        # Download Python installer with progress
        $pythonUrl = "https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe"
        $installerPath = "$env:TEMP\python-installer.exe"
        
        Write-Styled "Downloading Python installer (this may take a few minutes)..." -Color $Theme.Primary -Prefix "Download"
        Write-Styled "File size: ~25 MB" -Color $Theme.Info -Prefix "Info"
        
        # Download with progress
        $request = [System.Net.HttpWebRequest]::Create($pythonUrl)
        $request.UserAgent = "PowerShell Script"
        $response = $request.GetResponse()
        $totalLength = $response.ContentLength
        $responseStream = $response.GetResponseStream()
        $fileStream = [System.IO.File]::OpenWrite($installerPath)
        $buffer = New-Object byte[] 8192
        $bytesRead = 0
        $totalRead = 0
        $lastProgress = -1
        
        try {
            do {
                $bytesRead = $responseStream.Read($buffer, 0, $buffer.Length)
                if ($bytesRead -gt 0) {
                    $fileStream.Write($buffer, 0, $bytesRead)
                    $totalRead += $bytesRead
                    $progress = [math]::Round(($totalRead / $totalLength) * 100, 1)
                    if ($progress -ne $lastProgress) {
                        $downloadedMB = [math]::Round($totalRead / 1MB, 2)
                        $totalMB = [math]::Round($totalLength / 1MB, 2)
                        Write-Progress -Activity "Downloading Python Installer" -Status "$downloadedMB MB / $totalMB MB ($progress%)" -PercentComplete $progress
                        $lastProgress = $progress
                    }
                }
            } while ($bytesRead -gt 0)
        } finally {
            $fileStream.Close()
            $responseStream.Close()
            $response.Close()
        }
        Write-Progress -Activity "Downloading Python Installer" -Completed
        
        Write-Styled "Download completed!" -Color $Theme.Success -Prefix "Download"
        Write-Styled "Installing Python (this may take 2-5 minutes)..." -Color $Theme.Primary -Prefix "Install"
        Write-Styled "Please wait, do not close this window..." -Color $Theme.Warning -Prefix "Wait"
        
        # Show spinner while installing
        $installJob = Start-Job -ScriptBlock {
            param($path)
            $proc = Start-Process -FilePath $path -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -Wait -PassThru -NoNewWindow
            return $proc.ExitCode
        } -ArgumentList $installerPath
        
        $spinner = @('|', '/', '-', '\')
        $i = 0
        while ($installJob.State -eq 'Running') {
            $spinnerChar = $spinner[$i % $spinner.Length]
            Write-Host "`r[Installing Python... $spinnerChar] Please wait..." -NoNewline -ForegroundColor $Theme.Primary
            Start-Sleep -Milliseconds 300
            $i++
        }
        Write-Host "`r" -NoNewline
        
        $exitCode = Receive-Job $installJob
        Remove-Job $installJob
        
        if ($exitCode -ne 0 -and $exitCode -ne 3010) {
            throw "Python installer exited with code $exitCode"
        }
        
        # Refresh PATH
        Write-Styled "Refreshing environment variables..." -Color $Theme.Info -Prefix "Refresh"
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        # Verify installation with retries
        Write-Styled "Verifying Python installation..." -Color $Theme.Info -Prefix "Verify"
        $maxRetries = 10
        $retryCount = 0
        $installed = $false
        
        while ($retryCount -lt $maxRetries -and -not $installed) {
            Start-Sleep -Seconds 2
            if (Test-PythonInstalled) {
                $installed = $true
            } else {
                $retryCount++
                Write-Host "`r[Retry $retryCount/$maxRetries] Checking Python..." -NoNewline -ForegroundColor $Theme.Warning
            }
        }
        Write-Host "`r" -NoNewline
        
        if ($installed) {
            Write-Styled "Python installed successfully!" -Color $Theme.Success -Prefix "Success"
            return $true
        } else {
            throw "Python installation verification failed after $maxRetries retries"
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
            Write-Host "[Cloning...] Please wait..." -NoNewline -ForegroundColor $Theme.Primary
            git clone $RepoUrl $InstallPath 2>&1 | Out-Null
            Write-Host "`r" -NoNewline
            if ($LASTEXITCODE -eq 0) {
                Write-Styled "Repository cloned successfully!" -Color $Theme.Success -Prefix "Success"
                return $true
            } else {
                Write-Styled "Git clone failed, trying ZIP download..." -Color $Theme.Warning -Prefix "Fallback"
            }
        }
        
        # Fallback: Download as ZIP
        Write-Styled "Downloading repository as ZIP..." -Color $Theme.Info -Prefix "Download"
        
        # Parse GitHub URL to get user/repo
        if ($RepoUrl -match "github\.com[:/]([^/]+)/([^/]+)") {
            $githubUser = $matches[1]
            $repoName = $matches[2] -replace "\.git$", ""
            
            # Try main branch first, then master
            $zipUrl = "https://github.com/$githubUser/$repoName/archive/refs/heads/main.zip"
            $zipPath = "$env:TEMP\repo.zip"
            
            try {
                Write-Styled "Trying main branch..." -Color $Theme.Info -Prefix "Branch"
                # Download with progress
                $request = [System.Net.HttpWebRequest]::Create($zipUrl)
                $request.UserAgent = "PowerShell Script"
                $response = $request.GetResponse()
                $totalLength = $response.ContentLength
                $responseStream = $response.GetResponseStream()
                $fileStream = [System.IO.File]::OpenWrite($zipPath)
                $buffer = New-Object byte[] 8192
                $bytesRead = 0
                $totalRead = 0
                $lastProgress = -1
                
                try {
                    do {
                        $bytesRead = $responseStream.Read($buffer, 0, $buffer.Length)
                        if ($bytesRead -gt 0) {
                            $fileStream.Write($buffer, 0, $bytesRead)
                            $totalRead += $bytesRead
                            if ($totalLength -gt 0) {
                                $progress = [math]::Round(($totalRead / $totalLength) * 100, 1)
                                if ($progress -ne $lastProgress) {
                                    $downloadedMB = [math]::Round($totalRead / 1MB, 2)
                                    $totalMB = [math]::Round($totalLength / 1MB, 2)
                                    Write-Progress -Activity "Downloading Repository" -Status "$downloadedMB MB / $totalMB MB ($progress%)" -PercentComplete $progress
                                    $lastProgress = $progress
                                }
                            }
                        }
                    } while ($bytesRead -gt 0)
                } finally {
                    $fileStream.Close()
                    $responseStream.Close()
                    $response.Close()
                }
                Write-Progress -Activity "Downloading Repository" -Completed
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
        Write-Host "[Extracting...] Please wait..." -NoNewline -ForegroundColor $Theme.Primary
        Expand-Archive -Path $zipPath -DestinationPath $InstallPath -Force
        Remove-Item $zipPath
        Write-Host "`r" -NoNewline
        
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
        Write-Styled "Installing PyTorch (this may take 5-10 minutes)..." -Color $Theme.Info -Prefix "PyTorch"
        Write-Styled "PyTorch is a large package (~2GB), please be patient..." -Color $Theme.Warning -Prefix "Note"
        $pytorchJob = Start-Job -ScriptBlock {
            param($indexUrl)
            python -m pip install torch torchvision torchaudio --index-url $indexUrl 2>&1
            return $LASTEXITCODE
        } -ArgumentList "https://download.pytorch.org/whl/cpu"
        
        $spinner = @('|', '/', '-', '\')
        $i = 0
        while ($pytorchJob.State -eq 'Running') {
            $spinnerChar = $spinner[$i % $spinner.Length]
            Write-Host "`r[Installing PyTorch... $spinnerChar] This may take 5-10 minutes..." -NoNewline -ForegroundColor $Theme.Primary
            Start-Sleep -Milliseconds 500
            $i++
        }
        Write-Host "`r" -NoNewline
        $pytorchExit = Receive-Job $pytorchJob
        Remove-Job $pytorchJob
        
        if ($pytorchExit -ne 0) {
            Write-Styled "PyTorch installation had warnings, continuing..." -Color $Theme.Warning -Prefix "Warning"
        } else {
            Write-Styled "PyTorch installed successfully!" -Color $Theme.Success -Prefix "PyTorch"
        }
        
        # Install other requirements from requirements.txt
        Write-Styled "Installing other packages from requirements.txt..." -Color $Theme.Info -Prefix "Packages"
        $packagesJob = Start-Job -ScriptBlock {
            param($reqPath)
            python -m pip install -r $reqPath 2>&1
            return $LASTEXITCODE
        } -ArgumentList $requirementsPath
        
        $i = 0
        while ($packagesJob.State -eq 'Running') {
            $spinnerChar = $spinner[$i % $spinner.Length]
            Write-Host "`r[Installing packages... $spinnerChar] Please wait..." -NoNewline -ForegroundColor $Theme.Primary
            Start-Sleep -Milliseconds 300
            $i++
        }
        Write-Host "`r" -NoNewline
        $packagesExit = Receive-Job $packagesJob
        Remove-Job $packagesJob
        
        # Ensure all required packages are installed (backup list)
        $requiredPackages = @(
            "requests", "pillow", "numpy", "openpyxl", "pandas", 
            "matplotlib", "tqdm", "opencv-python", "fastapi", "uvicorn"
        )
        
        Write-Styled "Verifying all required packages are installed..." -Color $Theme.Info -Prefix "Verify"
        $missingPackages = @()
        foreach ($package in $requiredPackages) {
            python -m pip show $package 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $missingPackages += $package
            }
        }
        
        if ($missingPackages.Count -gt 0) {
            Write-Styled "Installing $($missingPackages.Count) missing packages..." -Color $Theme.Warning -Prefix "Missing"
            foreach ($package in $missingPackages) {
                Write-Host "[Installing $package...] " -NoNewline -ForegroundColor $Theme.Info
                python -m pip install $package 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✓" -ForegroundColor $Theme.Success
                } else {
                    Write-Host "✗" -ForegroundColor $Theme.Error
                }
            }
        }
        
        if ($packagesExit -eq 0 -or $missingPackages.Count -eq 0) {
            Write-Styled "All dependencies installed successfully!" -Color $Theme.Success -Prefix "Success"
            return $true
        } else {
            # Final retry with requirements.txt
            Write-Styled "Final retry with requirements.txt..." -Color $Theme.Warning -Prefix "Retry"
            python -m pip install -r $requirementsPath --ignore-installed 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Styled "Dependencies installed (with warnings)" -Color $Theme.Success -Prefix "Success"
                return $true
            }
            Write-Styled "Some packages may have failed, but continuing..." -Color $Theme.Warning -Prefix "Warning"
            return $true  # Continue anyway
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
    
    # Display installation path
    Write-Styled "Installation Path: $InstallPath" -Color $Theme.Info -Prefix "Path"
    Write-Styled "Repository: $RepoUrl" -Color $Theme.Info -Prefix "Repo"
    Write-Host ""
    
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
        Write-Styled "Code will be saved to: $InstallPath" -Color $Theme.Info -Prefix "Location"
        if (-not (Get-Repository -RepoUrl $RepoUrl -InstallPath $InstallPath)) {
            throw "Repository download failed"
        }
        Write-Styled "Repository downloaded to: $InstallPath" -Color $Theme.Success -Prefix "Location"
        
        # Step 3: Install Dependencies
        Write-Styled "Step 3: Installing dependencies..." -Color $Theme.Primary -Prefix "Step 3"
        Write-Styled "This may take several minutes, especially for PyTorch..." -Color $Theme.Warning -Prefix "Note"
        if (-not (Install-Dependencies -ProjectPath $InstallPath)) {
            Write-Styled "Warning: Some dependencies may have failed to install" -Color $Theme.Warning -Prefix "Warning"
            Write-Styled "You can try installing manually later" -Color $Theme.Info -Prefix "Info"
        }
        
        Write-Styled "`n✅ Installation completed successfully!" -Color $Theme.Success -Prefix "Complete"
        Write-Host ""
        Write-Styled "════════════════════════════════════════" -Color $Theme.Primary
        Write-Styled "Project location: $InstallPath" -Color $Theme.Success -Prefix "📁"
        Write-Styled "════════════════════════════════════════" -Color $Theme.Primary
        
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
    # Repository URL
    $repoUrl = "https://github.com/AdminCNTT/mart.git"
    
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
