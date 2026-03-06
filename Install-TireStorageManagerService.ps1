# Install-TireStorageManagerService.ps1
# Als Administrator ausführen!

# === Konfiguration (ANPASSEN) ===
$Repo = "https://github.com/tombo92/TireStorageManager"
$Nssm = "C:\tools\nssm\nssm.exe"        # Pfad zur nssm.exe
$ServiceName = "TireStorageManager"
$Port = 5000
$Secret = "your-long-secret"            # In Prod besser als System-Umgebungsvariable setzen
$LogsDir = Join-Path $Repo "logs"
$StartBat = Join-Path $Repo "start_server.bat"

# === Helper: Ermittele primäre IPv4 des Servers über Default-Route ===
function Get-PrimaryIPv4 {
    try {
        # 1) Standardroute ermitteln (0.0.0.0/0), bevorzugt die mit niedrigster Metrik
        $defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
                        Sort-Object -Property RouteMetric, InterfaceMetric |
                        Select-Object -First 1
        if (-not $defaultRoute) { return $null }

        # 2) IPv4-Adressen an diesem Interface holen (keine Loopback/APIPA)
        $ipv4s = Get-NetIPAddress -InterfaceIndex $defaultRoute.InterfaceIndex -AddressFamily IPv4 -ErrorAction Stop |
                 Where-Object {
                     $_.IPAddress -ne "127.0.0.1" -and
                     ($_.IPAddress -notmatch "^169\.254\.") -and
                     $_.PrefixLength -lt 32
                 } |
                 Sort-Object -Property SkipAsSource, AddressState

        if ($ipv4s -and $ipv4s[0].IPAddress) {
            return $ipv4s[0].IPAddress
        }
    } catch {
        # Ignorieren und unten Fallbacks verwenden
    }

    # Fallback 1: beste IPv4, die nicht Loopback/APIPA ist
    try {
        $any = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
               Where-Object { $_.IPAddress -ne "127.0.0.1" -and ($_.IPAddress -notmatch "^169\.254\.") } |
               Select-Object -First 1
        if ($any) { return $any.IPAddress }
    } catch {}

    # Fallback 2: Hostname/localhost
    return $null
}

# === Vorbereitungen ===
Write-Host "[setup] Prüfe Logs-Verzeichnis..."
New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

Write-Host "[setup] Prüfe venv & Waitress..."
$VenvActivate = Join-Path $Repo ".venv\Scripts\activate.ps1"
if (!(Test-Path $VenvActivate)) {
  Write-Host "[setup] Erzeuge venv..."
  & py -3 -m venv (Join-Path $Repo ".venv") | Out-Null
}
# Installiere waitress, falls nicht vorhanden
$WaitressExe = Join-Path $Repo ".venv\Scripts\waitress-serve.exe"
if (!(Test-Path $WaitressExe)) {
  Write-Host "[setup] Installiere waitress..."
  & powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location '$Repo'; .\.venv\Scripts\Activate.ps1; pip install waitress"
}

# === Dienst installieren: NSSM ruft deine Batch auf ===
Write-Host "[service] Installiere Dienst $ServiceName ..."
& "$Nssm" install $ServiceName "C:\Windows\System32\cmd.exe" "/c `"$StartBat`""

# Arbeitsverzeichnis setzen (wichtig für relative Pfade)
& "$Nssm" set $ServiceName AppDirectory "$Repo"

# Umgebung (optional)
& "$Nssm" set $ServiceName AppEnvironmentExtra "WHEELS_SECRET_KEY=$Secret"

# Logs (optional)
& "$Nssm" set $ServiceName AppStdout (Join-Path $LogsDir "waitress.out.log")
& "$Nssm" set $ServiceName AppStderr (Join-Path $LogsDir "waitress.err.log")

# Autostart
& "$Nssm" set $ServiceName Start SERVICE_AUTO_START

# Firewall öffnen (falls nötig)
Write-Host "[firewall] Öffne TCP-Port $Port (falls noch nicht freigeschaltet)..."
Try {
  New-NetFirewallRule -DisplayName "TireStorageManager $Port" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -ErrorAction Stop | Out-Null
} Catch {
  Write-Host "[firewall] Regel existiert evtl. bereits. Weiter..."
}

# Dienst starten
Write-Host "[service] Starte Dienst..."
Start-Service $ServiceName

# Status
Start-Sleep -Seconds 2
Get-Service $ServiceName | Format-Table -AutoSize

# === Ausgabe mit tatsächlicher Server-IP ===
$serverIp = Get-PrimaryIPv4
if ($serverIp) {
    Write-Host ("`n[done] Dienst installiert und gestartet. Aufruf: http://{0}:{1}" -f $serverIp, $Port)
} else {
    # Fallback: Hostname anzeigen, falls IP nicht ermittelbar
    $fqdn = try { (Get-CimInstance Win32_ComputerSystem).DNSHostName, (Get-CimInstance Win32_ComputerSystem).Domain -join "." } catch { $env:COMPUTERNAME }
    if (-not $fqdn -or $fqdn.Trim('.') -eq '') { $fqdn = $env:COMPUTERNAME }
    Write-Host ("`n[done] Dienst installiert und gestartet. Aufruf: http://{0}:{1} (IP konnte nicht eindeutig ermittelt werden)" -f $fqdn, $Port)
}