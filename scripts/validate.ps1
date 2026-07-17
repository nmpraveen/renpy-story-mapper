[CmdletBinding()]
param(
    [ValidateSet("Fast", "Focused", "Release")]
    [string]$Tier = "Fast",

    [Alias("Target")]
    [string[]]$PytestTarget,

    [switch]$IncludeBrowser,

    [string]$BrowserScript,

    [switch]$IncludePrivate,

    [string]$PrivateScript,

    [string[]]$PrivateArgument,

    [switch]$IncludeHardwareSensitive,

    [switch]$DryRun,

    [ValidateRange(0, 86400)]
    [int]$TimeoutSeconds = 0,

    [switch]$NoTimeout,

    [string]$Python
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Results = New-Object System.Collections.Generic.List[object]
$TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "renpy-story-mapper-validation-{0}" -f [guid]::NewGuid().ToString("N")
)

function Resolve-Tool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        throw "Required command '$Name' was not found on PATH."
    }
    return $command.Source
}

function Resolve-PythonCommand {
    if ($Python) {
        if (Test-Path -LiteralPath $Python -PathType Leaf) {
            return [pscustomobject]@{
                FilePath = [System.IO.Path]::GetFullPath($Python)
                Prefix = @()
            }
        }
        return [pscustomobject]@{
            FilePath = Resolve-Tool $Python
            Prefix = @()
        }
    }

    $venvPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return [pscustomobject]@{ FilePath = $venvPython; Prefix = @() }
    }

    $launcher = Get-Command "py" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $launcher) {
        return [pscustomobject]@{ FilePath = $launcher.Source; Prefix = @("-3.12") }
    }

    return [pscustomobject]@{ FilePath = Resolve-Tool "python"; Prefix = @() }
}

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (2 * $backslashes + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * (2 * $backslashes)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Format-Command {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $parts = @((ConvertTo-NativeArgument $FilePath))
    $parts += @($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ })
    return $parts -join " "
}

function Add-Step {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$DefaultTimeout,
        [string]$WorkingDirectory = $RepositoryRoot
    )

    $effectiveTimeout = $DefaultTimeout
    if ($NoTimeout) {
        $effectiveTimeout = 0
    }
    elseif ($TimeoutSeconds -gt 0) {
        $effectiveTimeout = $TimeoutSeconds
    }
    return [pscustomobject]@{
        Name = $Name
        FilePath = $FilePath
        Arguments = @($Arguments)
        TimeoutSeconds = $effectiveTimeout
        WorkingDirectory = $WorkingDirectory
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Step
    )

    $display = Format-Command $Step.FilePath $Step.Arguments
    if ($DryRun) {
        $timeoutLabel = if ($Step.TimeoutSeconds -gt 0) {
            "{0}s" -f $Step.TimeoutSeconds
        }
        else {
            "no timeout"
        }
        Write-Host ("[DRY RUN] {0} ({1})" -f $Step.Name, $timeoutLabel)
        Write-Host ("  {0}" -f $display)
        $Results.Add([pscustomobject]@{
            Name = $Step.Name
            Status = "planned"
            Seconds = 0.0
            ExitCode = 0
        })
        return $true
    }

    Write-Host ""
    Write-Host ("==> {0}" -f $Step.Name)
    Write-Host ("    {0}" -f $display)
    $started = Get-Date
    $timedOut = $false
    $exitCode = 1
    $stdout = ""
    $stderr = ""

    try {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $Step.FilePath
        $startInfo.Arguments = (@($Step.Arguments | ForEach-Object {
            ConvertTo-NativeArgument $_
        }) -join " ")
        $startInfo.WorkingDirectory = $Step.WorkingDirectory
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.EnvironmentVariables["PYTHONPATH"] = Join-Path $RepositoryRoot "src"
        $startInfo.EnvironmentVariables["PYTHONHASHSEED"] = "0"

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if ($Step.TimeoutSeconds -gt 0) {
            if (-not $process.WaitForExit($Step.TimeoutSeconds * 1000)) {
                $timedOut = $true
                & taskkill.exe /PID $process.Id /T /F *> $null
                $process.WaitForExit()
            }
            else {
                $process.WaitForExit()
            }
        }
        else {
            $process.WaitForExit()
        }
        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result
        if ($timedOut) {
            $exitCode = 124
        }
        else {
            $exitCode = $process.ExitCode
        }
        $process.Dispose()
    }
    catch {
        $stderr = $_.Exception.Message
        $exitCode = 1
    }

    if ($stdout.Trim().Length -gt 0) {
        Write-Host $stdout.TrimEnd()
    }
    if ($stderr.Trim().Length -gt 0) {
        Write-Host $stderr.TrimEnd()
    }

    $elapsed = ((Get-Date) - $started).TotalSeconds
    $status = "passed"
    if ($timedOut) {
        $status = "timed out"
    }
    elseif ($exitCode -ne 0) {
        $status = "failed"
    }
    $Results.Add([pscustomobject]@{
        Name = $Step.Name
        Status = $status
        Seconds = [math]::Round($elapsed, 2)
        ExitCode = $exitCode
    })
    return $exitCode -eq 0
}

function Python-Arguments {
    param([string[]]$Arguments)
    return @($PythonCommand.Prefix) + @($Arguments)
}

function Get-AcceptanceOutputOption {
    param([System.IO.FileInfo]$Script)

    $source = Get-Content -LiteralPath $Script.FullName -Raw
    if ($source.Contains('"--output-dir"')) {
        return "--output-dir"
    }
    if ($source.Contains('"--output"')) {
        return "--output"
    }
    throw ("Acceptance script {0} does not declare --output-dir or --output." -f $Script.FullName)
}

if ($Tier -eq "Focused" -and (!$PytestTarget -or $PytestTarget.Count -eq 0)) {
    throw "Focused validation requires at least one -PytestTarget."
}
if ($NoTimeout -and $TimeoutSeconds -gt 0) {
    throw "-NoTimeout cannot be combined with -TimeoutSeconds."
}
if ($BrowserScript -and -not $IncludeBrowser) {
    throw "-BrowserScript requires -IncludeBrowser."
}
if ($IncludeBrowser -and $Tier -ne "Release") {
    throw "Browser acceptance is available only with -Tier Release."
}
if ($PrivateScript -and -not $IncludePrivate) {
    throw "-PrivateScript requires -IncludePrivate."
}
if ($IncludePrivate -and $Tier -ne "Release") {
    throw "Private acceptance is available only with -Tier Release."
}
if ($IncludePrivate -and -not $PrivateScript) {
    throw "-IncludePrivate requires an explicit -PrivateScript."
}
if ($IncludeHardwareSensitive -and $Tier -ne "Release") {
    throw "Hardware-sensitive acceptance is available only with -Tier Release."
}

$PythonCommand = Resolve-PythonCommand
$steps = New-Object System.Collections.Generic.List[object]
$steps.Add((Add-Step -Name "Python version" -FilePath $PythonCommand.FilePath -DefaultTimeout 30 `
    -Arguments (Python-Arguments @(
        "-c",
        "import sys; assert (3, 12) <= sys.version_info[:2] < (3, 14), sys.version"
    ))))

if ($Tier -eq "Fast") {
    $steps.Add((Add-Step -Name "Ruff" -FilePath $PythonCommand.FilePath -DefaultTimeout 120 `
        -Arguments (Python-Arguments @("-m", "ruff", "check", "src", "tests", "scripts"))))
    $steps.Add((Add-Step -Name "Fast deterministic pytest" -FilePath $PythonCommand.FilePath `
        -DefaultTimeout 180 -Arguments (Python-Arguments @(
            "-m", "pytest", "-q", "tests/test_validation_script.py",
            "tests/test_workflow_contract.py", "tests/test_parser_graph.py",
            "tests/test_semantic.py"
        ))))
}
elseif ($Tier -eq "Focused") {
    $steps.Add((Add-Step -Name "Ruff" -FilePath $PythonCommand.FilePath -DefaultTimeout 120 `
        -Arguments (Python-Arguments @("-m", "ruff", "check", "src", "tests", "scripts"))))
    $focusedArguments = @("-m", "pytest", "-q") + @($PytestTarget)
    $steps.Add((Add-Step -Name "Focused pytest" -FilePath $PythonCommand.FilePath `
        -DefaultTimeout 600 -Arguments (Python-Arguments $focusedArguments)))
}
else {
    $pytestArguments = @("-m", "pytest", "-q")
    if (-not $IncludeHardwareSensitive) {
        $pytestArguments += @("-m", "not hardware_sensitive")
    }
    $steps.Add((Add-Step -Name "Full deterministic pytest" -FilePath $PythonCommand.FilePath `
        -DefaultTimeout 900 -Arguments (Python-Arguments $pytestArguments)))
    $steps.Add((Add-Step -Name "Ruff" -FilePath $PythonCommand.FilePath -DefaultTimeout 180 `
        -Arguments (Python-Arguments @("-m", "ruff", "check", "src", "tests", "scripts"))))
    $steps.Add((Add-Step -Name "Strict mypy" -FilePath $PythonCommand.FilePath -DefaultTimeout 300 `
        -Arguments (Python-Arguments @("-m", "mypy", "--strict", "src/renpy_story_mapper"))))
    $steps.Add((Add-Step -Name "Installed dependency check" -FilePath $PythonCommand.FilePath `
        -DefaultTimeout 60 -Arguments (Python-Arguments @("-m", "pip", "check"))))

    $javascriptFiles = @(Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot "src") `
        -Filter "*.js" -File -Recurse | Sort-Object FullName)
    if ($javascriptFiles.Count -gt 0) {
        $node = $null
        try {
            $node = Resolve-Tool "node"
        }
        catch {
            if (-not $DryRun) {
                throw
            }
            $node = "node"
        }
        foreach ($javascriptFile in $javascriptFiles) {
            $relative = $javascriptFile.FullName.Substring($RepositoryRoot.Length + 1)
            $steps.Add((Add-Step -Name ("JavaScript syntax: {0}" -f $relative) `
                -FilePath $node -DefaultTimeout 30 -Arguments @("--check", $javascriptFile.FullName)))
        }
    }

    $git = Resolve-Tool "git"
    $steps.Add((Add-Step -Name "Whitespace check" -FilePath $git -DefaultTimeout 60 `
        -Arguments @("diff", "--check")))

    $distributionDirectory = Join-Path $TemporaryRoot "dist"
    $steps.Add((Add-Step -Name "Build isolated sdist and wheel" -FilePath $PythonCommand.FilePath `
        -DefaultTimeout 300 -Arguments (Python-Arguments @(
            "-m", "build", "--sdist", "--wheel", "--outdir", $distributionDirectory, "."
        ))))

    if ($IncludeHardwareSensitive) {
        $scaleScripts = @(Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot "scripts") `
            -Filter "*_scale_acceptance.py" -File | Sort-Object Name)
        foreach ($scaleScript in $scaleScripts) {
            $scaleOutput = Join-Path $TemporaryRoot ("scale-" + $scaleScript.BaseName)
            $scaleOutputOption = Get-AcceptanceOutputOption $scaleScript
            $steps.Add((Add-Step `
                -Name ("Opt-in hardware-sensitive acceptance: {0}" -f $scaleScript.Name) `
                -FilePath $PythonCommand.FilePath -DefaultTimeout 300 `
                -Arguments (Python-Arguments @(
                    $scaleScript.FullName, $scaleOutputOption, $scaleOutput
                ))))
        }
    }

    if ($IncludeBrowser) {
        $selectedBrowserScript = $null
        if ($BrowserScript) {
            $selectedBrowserScript = Get-Item -LiteralPath $BrowserScript -ErrorAction Stop
        }
        else {
            $selectedBrowserScript = Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot "scripts") `
                -Filter "*_browser_acceptance.py" -File | Sort-Object Name | Select-Object -Last 1
        }
        if ($null -eq $selectedBrowserScript) {
            throw "-IncludeBrowser was requested, but no *_browser_acceptance.py script exists."
        }
        $browserOutput = Join-Path $TemporaryRoot ("browser-" + $selectedBrowserScript.BaseName)
        $browserOutputOption = Get-AcceptanceOutputOption $selectedBrowserScript
        $steps.Add((Add-Step -Name ("Opt-in browser acceptance: {0}" -f $selectedBrowserScript.Name) `
            -FilePath $PythonCommand.FilePath -DefaultTimeout 900 `
            -Arguments (Python-Arguments @(
                $selectedBrowserScript.FullName, $browserOutputOption, $browserOutput
            ))))
    }

    if ($IncludePrivate) {
        $selectedPrivateScript = Get-Item -LiteralPath $PrivateScript -ErrorAction Stop
        if (-not $selectedPrivateScript.Name.EndsWith("_private_acceptance.py")) {
            throw "-PrivateScript must name a *_private_acceptance.py harness."
        }
        $steps.Add((Add-Step -Name ("Opt-in private acceptance: {0}" -f `
            $selectedPrivateScript.Name) -FilePath $PythonCommand.FilePath -DefaultTimeout 1800 `
            -Arguments (Python-Arguments (@($selectedPrivateScript.FullName) + `
                @($PrivateArgument)))))
    }
}

$allPassed = $true
try {
    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
    }

    foreach ($step in $steps) {
        if (-not (Invoke-Step $step)) {
            $allPassed = $false
        }

        if ($Tier -eq "Release" -and $step.Name -eq "Build isolated sdist and wheel") {
            if ($DryRun) {
                $installTarget = Join-Path $TemporaryRoot "installed-wheel"
                $plannedWheel = Join-Path $distributionDirectory "<built-wheel>.whl"
                $installStep = Add-Step -Name "Install built wheel into isolated target" `
                    -FilePath $PythonCommand.FilePath -DefaultTimeout 180 `
                    -Arguments (Python-Arguments @(
                        "-m", "pip", "install", "--no-deps", "--target", $installTarget, $plannedWheel
                    ))
                [void](Invoke-Step $installStep)
                $verifyStep = Add-Step -Name "Import installed wheel and verify browser assets" `
                    -FilePath $PythonCommand.FilePath -DefaultTimeout 60 `
                    -Arguments (Python-Arguments @("-I", "-c", "<isolated package verification>"))
                [void](Invoke-Step $verifyStep)
            }
            elseif ($Results[$Results.Count - 1].Status -eq "passed") {
                $wheels = @(Get-ChildItem -LiteralPath $distributionDirectory -Filter "*.whl" -File)
                $sdists = @(Get-ChildItem -LiteralPath $distributionDirectory `
                    -Filter "*.tar.gz" -File)
                if ($wheels.Count -ne 1 -or $sdists.Count -ne 1) {
                    Write-Host ("Expected one wheel and one sdist in {0}; found {1} and {2}." -f `
                        $distributionDirectory, $wheels.Count, $sdists.Count)
                    $Results.Add([pscustomobject]@{
                        Name = "Locate built distributions"
                        Status = "failed"
                        Seconds = 0.0
                        ExitCode = 1
                    })
                    $allPassed = $false
                }
                else {
                    $installTarget = Join-Path $TemporaryRoot "installed-wheel"
                    $installStep = Add-Step -Name "Install built wheel into isolated target" `
                        -FilePath $PythonCommand.FilePath -DefaultTimeout 180 `
                        -Arguments (Python-Arguments @(
                            "-m", "pip", "install", "--no-deps", "--target", $installTarget,
                            $wheels[0].FullName
                        ))
                    $installed = Invoke-Step $installStep
                    if (-not $installed) {
                        $allPassed = $false
                    }
                    else {
                        $verification = @"
import importlib.resources as resources
import json
import sys
sys.path.insert(0, r'$installTarget')
import renpy_story_mapper
import renpy_story_mapper.cli
import renpy_story_mapper.web
static = resources.files('renpy_story_mapper.web').joinpath('static')
manifest_path = static.joinpath('asset-manifest.json')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
required = ('asset-manifest.json', *manifest['assets'])
missing = [name for name in required if not static.joinpath(name).is_file()]
assert not missing, f'missing packaged browser assets: {missing}'
notice = resources.files('renpy_story_mapper').joinpath('THIRD_PARTY_NOTICES.md')
assert notice.is_file(), 'missing packaged third-party notice'
print(f'isolated import: {renpy_story_mapper.__file__}')
"@
                        $verifyStep = Add-Step `
                            -Name "Import installed wheel and verify browser assets" `
                            -FilePath $PythonCommand.FilePath -DefaultTimeout 60 `
                            -WorkingDirectory $TemporaryRoot `
                            -Arguments (Python-Arguments @("-I", "-c", $verification))
                        if (-not (Invoke-Step $verifyStep)) {
                            $allPassed = $false
                        }
                    }
                }
            }
        }
    }
}
finally {
    if (-not $DryRun -and (Test-Path -LiteralPath $TemporaryRoot)) {
        Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
    }
}

Write-Host ""
Write-Host ("Validation summary ({0})" -f $Tier.ToLowerInvariant())
$Results | Format-Table -AutoSize Name, Status, Seconds, ExitCode

if (-not $allPassed) {
    exit 1
}
exit 0
