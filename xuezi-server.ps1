$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$port = 8765
$listener = $null
$userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36 XUEZI/1.1.0"

function ConvertTo-PlainText([string]$value) {
  if ([string]::IsNullOrWhiteSpace($value)) { return "" }
  $decoded = [Net.WebUtility]::HtmlDecode($value)
  return (($decoded -replace '<[^>]+>', ' ') -replace '\s+', ' ').Trim()
}

function Test-AllowedResourceHost([string]$url, [string]$type) {
  try { $hostName = ([Uri]$url).Host.ToLowerInvariant() } catch { return $false }
  $blocked = @("bing.com", "www.bing.com", "baidu.com", "www.baidu.com", "google.com", "example.com", "localhost")
  if ($blocked -contains $hostName) { return $false }
  if ($type -eq "video") {
    return $hostName -eq "b23.tv" -or $hostName.EndsWith("bilibili.com") -or $hostName.EndsWith("icourse163.org") -or $hostName.EndsWith("xuetangx.com")
  }
  return $true
}

function Test-ResourcePage([string]$url, [string]$type) {
  if (-not (Test-AllowedResourceHost $url $type)) { return $null }
  try {
    $resourceUri = [Uri]$url
    if ($type -eq "video" -and $resourceUri.Host.ToLowerInvariant().EndsWith("bilibili.com")) {
      $videoMatch = [regex]::Match($resourceUri.AbsolutePath, '/video/(?<id>BV[0-9A-Za-z]{10}|av[0-9]+)', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
      if (-not $videoMatch.Success) { return $null }
      $videoId = $videoMatch.Groups['id'].Value
      $parameter = if ($videoId.StartsWith('BV', [StringComparison]::OrdinalIgnoreCase)) { "bvid=$videoId" } else { "aid=$($videoId.Substring(2))" }
      $apiUrl = "https://api.bilibili.com/x/web-interface/view?$parameter"
      $apiResponse = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 10 -Headers @{ "User-Agent" = $userAgent; "Referer" = "https://www.bilibili.com/" }
      if ([int]$apiResponse.code -ne 0 -or [int]$apiResponse.data.state -lt 0) { return $null }
      return [pscustomobject]@{
        url = "https://www.bilibili.com/video/$($apiResponse.data.bvid)/"
        status = 200
        contentType = "text/html"
        checkedAt = [DateTime]::UtcNow.ToString("o")
        title = [string]$apiResponse.data.title
      }
    }
    if ($type -eq "paper" -and $resourceUri.Host.ToLowerInvariant() -eq "doi.org") {
      $doi = [Uri]::UnescapeDataString($resourceUri.AbsolutePath.TrimStart('/'))
      if ([string]::IsNullOrWhiteSpace($doi)) { return $null }
      $crossrefUrl = "https://api.crossref.org/works/$([Uri]::EscapeDataString($doi))"
      $crossref = Invoke-RestMethod -Uri $crossrefUrl -TimeoutSec 10 -Headers @{ "User-Agent" = $userAgent }
      if (-not $crossref.message.DOI) { return $null }
      return [pscustomobject]@{
        url = "https://doi.org/$($crossref.message.DOI)"
        status = 200
        contentType = "text/html"
        checkedAt = [DateTime]::UtcNow.ToString("o")
        title = [string]@($crossref.message.title)[0]
      }
    }
  } catch {
    return $null
  }
  $request = $null
  $response = $null
  try {
    $request = [Net.HttpWebRequest]::Create($url)
    $request.Method = "GET"
    $request.UserAgent = $userAgent
    $request.Accept = "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5"
    $request.AllowAutoRedirect = $true
    $request.MaximumAutomaticRedirections = 6
    $request.Timeout = 7000
    $request.ReadWriteTimeout = 7000
    $request.AddRange(0, 8191)
    $response = [Net.HttpWebResponse]$request.GetResponse()
    $statusCode = [int]$response.StatusCode
    $finalUrl = $response.ResponseUri.AbsoluteUri
    if ($statusCode -lt 200 -or $statusCode -ge 400 -or -not (Test-AllowedResourceHost $finalUrl $type)) { return $null }
    return [pscustomobject]@{
      url = $finalUrl
      status = $statusCode
      contentType = [string]$response.ContentType
      checkedAt = [DateTime]::UtcNow.ToString("o")
    }
  } catch {
    return $null
  } finally {
    if ($response) { $response.Dispose() }
  }
}

function Get-BraveSearchCandidates([string]$expression) {
  $encoded = [Uri]::EscapeDataString($expression)
  $searchUrl = "https://search.brave.com/search?q=$encoded&source=web"
  $headers = @{ "User-Agent" = $userAgent; "Accept-Language" = "zh-CN,zh;q=0.9" }
  $response = Invoke-WebRequest -Uri $searchUrl -UseBasicParsing -TimeoutSec 15 -Headers $headers
  $pattern = '<a href="(?<url>https?://[^"]+)"[^>]*class="[^"]*\bl1\b[^"]*"[\s\S]{0,4200}?<div class="title search-snippet-title[^"]*" title="(?<title>[^"]+)"'
  $matches = [regex]::Matches($response.Content, $pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase)
  $items = @()
  foreach ($match in $matches) {
    $items += [pscustomobject]@{
      title = ConvertTo-PlainText ([Net.WebUtility]::HtmlDecode($match.Groups['title'].Value))
      link = [Net.WebUtility]::HtmlDecode($match.Groups['url'].Value)
      description = ""
      source = "Brave live search"
    }
  }
  return $items
}

function Get-BilibiliCandidates([string]$query) {
  $headers = @{ "User-Agent" = $userAgent; "Referer" = "https://www.bilibili.com/" }
  $nav = Invoke-RestMethod -Uri "https://api.bilibili.com/x/web-interface/nav" -Headers $headers -TimeoutSec 12
  $imgKey = [IO.Path]::GetFileNameWithoutExtension(([Uri]$nav.data.wbi_img.img_url).AbsolutePath)
  $subKey = [IO.Path]::GetFileNameWithoutExtension(([Uri]$nav.data.wbi_img.sub_url).AbsolutePath)
  $rawKey = $imgKey + $subKey
  $mixinTable = @(46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)
  $mixinKey = (-join ($mixinTable | ForEach-Object { $rawKey[$_] })).Substring(0, 32)
  $parameters = [ordered]@{
    keyword = $query
    page = "1"
    page_size = "20"
    search_type = "video"
    wts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
  }
  $pairs = @()
  foreach ($key in ($parameters.Keys | Sort-Object)) {
    $value = ([string]$parameters[$key]) -replace "[!'()*]", ""
    $pairs += [Uri]::EscapeDataString($key) + "=" + [Uri]::EscapeDataString($value)
  }
  $queryString = $pairs -join "&"
  $md5 = [Security.Cryptography.MD5]::Create()
  try {
    $signature = ($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($queryString + $mixinKey)) | ForEach-Object { $_.ToString("x2") }) -join ""
  } finally {
    $md5.Dispose()
  }
  $url = "https://api.bilibili.com/x/web-interface/wbi/search/type?$queryString&w_rid=$signature"
  $response = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 18
  if ([int]$response.code -ne 0) { throw "Bilibili search returned code $($response.code)" }
  $items = @()
  foreach ($video in @($response.data.result)) {
    if (-not $video.bvid) { continue }
    $items += [pscustomobject]@{
      title = ConvertTo-PlainText ([string]$video.title)
      link = "https://www.bilibili.com/video/$($video.bvid)/"
      description = ConvertTo-PlainText (([string]$video.author) + " " + ([string]$video.description))
      source = "Bilibili live search"
    }
  }
  return $items
}

function Get-CrossrefCandidates([string]$query) {
  $encoded = [Uri]::EscapeDataString($query)
  $url = "https://api.crossref.org/works?query.bibliographic=$encoded&rows=12&select=DOI,title,publisher,published"
  $response = Invoke-RestMethod -Uri $url -TimeoutSec 15 -Headers @{ "User-Agent" = "$userAgent mailto:local@xuezi.invalid" }
  $items = @()
  foreach ($work in @($response.message.items)) {
    if (-not $work.DOI -or -not @($work.title).Count) { continue }
    $year = ""
    try { $year = [string]$work.published.'date-parts'[0][0] } catch { }
    $items += [pscustomobject]@{
      title = ConvertTo-PlainText ([string]@($work.title)[0])
      link = "https://doi.org/$($work.DOI)"
      description = (([string]$work.publisher) + $(if ($year) { " ($year)" } else { "" })).Trim()
      source = "Crossref DOI registry"
    }
  }
  return $items
}

function Get-TavilyCandidates([string]$expression, [string]$apiKey) {
  if ([string]::IsNullOrWhiteSpace($apiKey)) { return @() }
  $requestBody = @{
    api_key = $apiKey
    query = $expression
    search_depth = "advanced"
    max_results = 12
    include_answer = $false
    include_raw_content = $false
  } | ConvertTo-Json -Depth 4 -Compress
  $response = Invoke-RestMethod -Uri "https://api.tavily.com/search" -Method Post -ContentType "application/json" -Body $requestBody -TimeoutSec 25
  $items = @()
  foreach ($result in @($response.results)) {
    if (-not $result.url -or -not $result.title) { continue }
    $items += [pscustomobject]@{
      title = ConvertTo-PlainText ([string]$result.title)
      link = [string]$result.url
      description = ConvertTo-PlainText ([string]$result.content)
      source = "Tavily live search"
    }
  }
  return $items
}

function Get-SearchExpression([string]$query, [string]$type) {
  switch ($type) {
    "video" { return "$query site:bilibili.com/video" }
    "website" { return "$query (site:edu.cn OR site:gov.cn OR site:icourse163.org OR site:xuetangx.com)" }
    "paper" { return "$query paper review (site:cnki.net OR site:nssd.cn OR site:doi.org OR site:edu.cn)" }
    "book" { return "$query textbook monograph (site:nlc.cn OR site:book.douban.com OR site:press.cn)" }
    default { return $query }
  }
}

function Get-SearchCandidateScore($item, [string]$query, [string]$type) {
  $title = (ConvertTo-PlainText ([string]$item.title)).ToLowerInvariant()
  $score = 0
  $genericTerms = @("teaching", "tutorial", "course", "paper", "review", "textbook", "monograph")
  foreach ($term in ($query -split '\s+')) {
    $normalized = $term.Trim().ToLowerInvariant()
    if ($normalized.Length -lt 2 -or $genericTerms -contains $normalized) { continue }
    if ($title.Contains($normalized)) { $score += [Math]::Min(30, 4 + $normalized.Length * 3) }
  }
  if ($type -eq "video" -and ([string]$item.link) -match 'bilibili\.com/video/') { $score += 8 }
  if ($type -eq "website" -and ([string]$item.link) -match '\.(edu|gov)\.cn/') { $score += 8 }
  return $score
}

function Search-VerifiedResources([string]$query, [string]$type, [int]$limit, [string]$searchApiKey) {
  $expression = Get-SearchExpression $query $type
  $items = @()
  if ($type -eq "video") {
    try { $items = @(Get-BilibiliCandidates $query) } catch { $items = @() }
  } elseif (-not [string]::IsNullOrWhiteSpace($searchApiKey)) {
    try { $items = @(Get-TavilyCandidates $expression $searchApiKey) } catch { $items = @() }
  } elseif ($type -eq "paper") {
    $items = @(Get-CrossrefCandidates $query)
  } else {
    try { $items = @(Get-BraveSearchCandidates $expression) } catch { $items = @() }
  }
  if (-not $items.Count -and $type -ne "book") {
    $encoded = [Uri]::EscapeDataString($expression)
    $searchUrl = "https://www.bing.com/search?format=rss&setlang=zh-CN&cc=CN&count=20&q=$encoded"
    $headers = @{ "User-Agent" = $userAgent; "Accept-Language" = "zh-CN,zh;q=0.9" }
    $searchResponse = Invoke-WebRequest -Uri $searchUrl -UseBasicParsing -TimeoutSec 15 -Headers $headers
    [xml]$rss = $searchResponse.Content
    $items = @($rss.rss.channel.item)
  }
  $items = @($items | Sort-Object -Property @{ Expression = { Get-SearchCandidateScore $_ $query $type }; Descending = $true })
  $results = @()
  $seen = @{}
  $primaryTerm = @($query -split '\s+' | Where-Object { $_.Trim().Length -ge 2 })[0]
  foreach ($item in $items) {
    if ($results.Count -ge $limit) { break }
    $candidateTitle = ConvertTo-PlainText ([string]$item.title)
    if ($primaryTerm -and $type -ne "book" -and -not $candidateTitle.ToLowerInvariant().Contains($primaryTerm.ToLowerInvariant())) { continue }
    $candidateUrl = [string]$item.link
    if ([string]::IsNullOrWhiteSpace($candidateUrl) -or $seen.ContainsKey($candidateUrl)) { continue }
    $seen[$candidateUrl] = $true
    $verified = Test-ResourcePage $candidateUrl $type
    if ($null -eq $verified) { continue }
    $title = if ($verified.title) { ConvertTo-PlainText ([string]$verified.title) } else { ConvertTo-PlainText ([string]$item.title) }
    if ([string]::IsNullOrWhiteSpace($title)) { continue }
    $summary = ConvertTo-PlainText ([string]$item.description)
    $results += [pscustomobject]@{
      type = $type
      name = $title
      url = $verified.url
      summary = $summary
      note = ""
      source = if ($item.source) { [string]$item.source } else { "Bing live search" }
      verified = $true
      checkedAt = $verified.checkedAt
    }
  }
  return $results
}

function Write-Response($stream, [string]$status, [string]$contentType, [byte[]]$body) {
  $header = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
  $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)
  $stream.Write($headerBytes, 0, $headerBytes.Length)
  $stream.Write($body, 0, $body.Length)
  $stream.Flush()
}

function Get-QueryValue([Uri]$uri, [string]$name) {
  foreach ($pair in $uri.Query.TrimStart('?').Split('&')) {
    if ([string]::IsNullOrWhiteSpace($pair)) { continue }
    $parts = $pair -split '=', 2
    $key = [Uri]::UnescapeDataString($parts[0].Replace('+', ' '))
    if ($key -ne $name) { continue }
    if ($parts.Length -lt 2) { return "" }
    return [Uri]::UnescapeDataString($parts[1].Replace('+', ' '))
  }
  return ""
}

for ($candidatePort = 8765; $candidatePort -le 8785; $candidatePort += 1) {
  try {
    $testListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidatePort)
    $testListener.Start()
    $listener = $testListener
    $port = $candidatePort
    break
  } catch {
    if ($testListener) { $testListener.Stop() }
  }
}
if ($null -eq $listener) { exit 1 }

$mime = @{
  ".html" = "text/html; charset=utf-8"; ".js" = "text/javascript; charset=utf-8"; ".css" = "text/css; charset=utf-8"
  ".json" = "application/json; charset=utf-8"; ".pdf" = "application/pdf"; ".wasm" = "application/wasm"
  ".gz" = "application/gzip"; ".png" = "image/png"; ".jpg" = "image/jpeg"; ".svg" = "image/svg+xml"
}

if ($env:XUEZI_NO_BROWSER -ne "1") {
  Start-Process ("http://127.0.0.1:$port/index.html")
}

while ($true) {
  $client = $listener.AcceptTcpClient()
  $stream = $null
  try {
    $stream = $client.GetStream()
    $stream.ReadTimeout = 5000
    $stream.WriteTimeout = 15000
    $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 4096, $true)
    $requestLine = $reader.ReadLine()
    if ($null -eq $requestLine) { continue }
    $requestHeaders = @{}
    $headerLine = $reader.ReadLine()
    while ($null -ne $headerLine -and $headerLine -ne "") {
      $headerParts = $headerLine -split ':', 2
      if ($headerParts.Length -eq 2) { $requestHeaders[$headerParts[0].Trim().ToLowerInvariant()] = $headerParts[1].Trim() }
      $headerLine = $reader.ReadLine()
    }
    $parts = $requestLine -split " ", 3
    $target = if ($parts.Length -gt 1) { $parts[1] } else { "/" }
    $uri = [Uri]::new("http://127.0.0.1$target")

    if ($uri.AbsolutePath -eq "/api/resource-search") {
      try {
        $query = Get-QueryValue $uri "q"
        $type = Get-QueryValue $uri "type"
        $limit = 3
        [void][int]::TryParse((Get-QueryValue $uri "limit"), [ref]$limit)
        $limit = [Math]::Max(1, [Math]::Min(5, $limit))
        if ([string]::IsNullOrWhiteSpace($query) -or @("video", "website", "paper", "book") -notcontains $type) {
          throw "Invalid search query or resource type"
        }
        $searchApiKey = [string]$requestHeaders["x-xuezi-search-key"]
        $results = @(Search-VerifiedResources $query $type $limit $searchApiKey)
        $payload = @{ ok = $true; source = "Live search with URL validation"; query = $query; results = $results } | ConvertTo-Json -Depth 6 -Compress
        Write-Response $stream "200 OK" "application/json; charset=utf-8" ([Text.Encoding]::UTF8.GetBytes($payload))
      } catch {
        $message = $_.Exception.Message
        $line = $_.InvocationInfo.ScriptLineNumber
        $payload = @{ ok = $false; error = "Live search failed at line ${line}: $message"; results = @() } | ConvertTo-Json -Depth 4 -Compress
        Write-Response $stream "502 Bad Gateway" "application/json; charset=utf-8" ([Text.Encoding]::UTF8.GetBytes($payload))
      }
      continue
    }

    $relative = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
    if ([string]::IsNullOrWhiteSpace($relative)) { $relative = "index.html" }
    $candidate = [IO.Path]::GetFullPath((Join-Path $root ($relative -replace '/', '\')))
    $insideRoot = $candidate.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
    if ($insideRoot -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      $body = [IO.File]::ReadAllBytes($candidate)
      $contentType = $mime[[IO.Path]::GetExtension($candidate).ToLowerInvariant()]
      if (-not $contentType) { $contentType = "application/octet-stream" }
      Write-Response $stream "200 OK" $contentType $body
    } else {
      Write-Response $stream "404 Not Found" "text/plain; charset=utf-8" ([Text.Encoding]::UTF8.GetBytes("Not Found"))
    }
  } catch { }
  finally {
    if ($stream) { $stream.Dispose() }
    $client.Dispose()
  }
}
