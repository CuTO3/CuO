param([switch]$NoBrowser)

# 本地端口可用时沿用常用地址，否则在其后九个端口中选择。
$ErrorActionPreference = 'Stop'
$ssh = (Get-Command ssh.exe -CommandType Application).Source
$pages = @(
    @{ Name = 'CuO 控制台'; Remote = 8080; Local = 9080; Path = '/console/' }
    @{ Name = 'NapCat WebUI'; Remote = 6099; Local = 6099; Path = '/webui/' }
    @{ Name = 'LiteLLM 管理界面'; Remote = 8888; Local = 8888; Path = '/ui/' }
    @{ Name = 'Syncthing 管理界面'; Remote = 8384; Local = 9090; Path = '/' }
)
$tunnels = @{}

function Stop-PageTunnels {
    foreach ($tunnel in $tunnels.Values) {
        if (-not $tunnel.Process.HasExited) {
            try {
                $tunnel.Process.Kill()
                $null = $tunnel.Process.WaitForExit(1000)
            }
            catch { if (-not $tunnel.Process.HasExited) { Write-Warning $_ } }
        }
        $tunnel.Process.Dispose()
        Remove-Item -LiteralPath $tunnel.Log -ErrorAction SilentlyContinue
    }
    $tunnels.Clear()
}

function Open-Page($page) {
    $tunnel = $tunnels[$page.Name]
    if ($tunnel -and -not $tunnel.Process.HasExited) {
        Write-Host "$($page.Name)  $($tunnel.Url)"
        if (-not $NoBrowser) { Start-Process $tunnel.Url }
        return
    }
    if ($tunnel) {
        $tunnel.Process.Dispose()
        Remove-Item -LiteralPath $tunnel.Log -ErrorAction SilentlyContinue
        $tunnels.Remove($page.Name)
    }

    $occupied = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port
    $port = $page.Local..($page.Local + 9) | Where-Object { $_ -notin $occupied } | Select-Object -First 1
    if (-not $port) { throw "从 $($page.Local) 开始的十个本地端口均已占用。" }
    $forward = "127.0.0.1:${port}:127.0.0.1:$($page.Remote)"
    $log = New-TemporaryFile
    $process = $null
    try {
        $process = Start-Process -FilePath $ssh -WindowStyle Hidden -PassThru -RedirectStandardError $log.FullName -ArgumentList @(
            '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3', '-L', $forward, 'cucl'
        )
        $deadline = [DateTime]::UtcNow.AddSeconds(12)
        do {
            if ($process.HasExited) {
                $detail = (Get-Content -LiteralPath $log.FullName -Raw)
                throw "SSH 隧道启动失败（退出码 $($process.ExitCode)）。$detail"
            }
            $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -OwningProcess $process.Id -ErrorAction SilentlyContinue
            if ($listener) { break }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $listener) { throw '等待 SSH 隧道超时。' }

        $url = "http://127.0.0.1:${port}$($page.Path)"
        $tunnels[$page.Name] = @{ Process = $process; Url = $url; Log = $log.FullName }
        Write-Host "$($page.Name)  $url"
    } catch {
        if ($process) {
            if (-not $process.HasExited) {
                $process.Kill()
                $null = $process.WaitForExit(1000)
            }
            $process.Dispose()
        }
        throw
    } finally {
        # SSH 在运行时可能仍持有日志文件，退出时再清理。
        if (-not $tunnels.ContainsKey($page.Name)) {
            Remove-Item -LiteralPath $log.FullName -ErrorAction SilentlyContinue
        }
    }
    if (-not $NoBrowser) { Start-Process $url }
}

try {
    while ($true) {
        Write-Host "`nCuCl 管理页面"
        for ($i = 0; $i -lt $pages.Count; $i++) {
            $page = $pages[$i]
            $tunnel = $tunnels[$page.Name]
            $state = if ($tunnel -and -not $tunnel.Process.HasExited) { $tunnel.Url } else { '待打开' }
            Write-Host "  $($i + 1)  $($page.Name)  [$state]"
        }
        Write-Host '  0  退出并关闭本次隧道'
        $choice = Read-Host '输入编号'
        if ($null -eq $choice -or $choice.Trim() -eq '0') { break }
        $choice = $choice.Trim()
        if ($choice -notmatch '^[1-4]$') { continue }
        try { Open-Page $pages[[int]$choice - 1] }
        catch { Write-Warning $_.Exception.Message }
    }
} finally {
    Stop-PageTunnels
}
