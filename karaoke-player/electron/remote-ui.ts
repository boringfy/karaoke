/**
 * The phone-facing remote UI, served inline by remote-server.
 *
 * Deliberately a single self-contained document: no build step, no bundle to
 * keep in sync with the desktop renderer, and it stays installable as a PWA
 * ("Add to Home screen") without any store or toolchain.
 */

export function remoteManifest(): string {
  return JSON.stringify({
    name: 'Karaoke Remote',
    short_name: 'Karaoke',
    display: 'standalone',
    background_color: '#111318',
    theme_color: '#111318',
    start_url: '/',
    icons: [],
  })
}

export function remoteUiHtml(): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111318">
<link rel="manifest" href="/manifest.webmanifest">
<title>Karaoke Remote</title>
<style>
  :root{--bg:#111318;--panel:#1a1d25;--panel2:#222633;--fg:#e9ecf4;--dim:#98a0b5;
        --accent:#6aa9ff;--danger:#ff6b6b;--border:#2c313f}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
  header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--border);
         padding:12px 16px;z-index:5}
  h1{font-size:15px;margin:0;letter-spacing:.04em;text-transform:uppercase;color:var(--dim)}
  main{padding:16px;padding-bottom:40px;max-width:640px;margin:0 auto}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;
        padding:14px;margin-bottom:16px}
  .now-title{font-size:20px;font-weight:600;margin:2px 0}
  .now-artist{color:var(--dim);font-size:14px}
  .muted{color:var(--dim)}
  button{font:inherit;color:var(--fg);background:var(--panel2);border:1px solid var(--border);
         border-radius:10px;padding:11px 14px;cursor:pointer;min-height:44px}
  button:active{transform:scale(.98)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#08101f;font-weight:600}
  button.danger{background:transparent;border-color:transparent;color:var(--danger);
                padding:8px 10px;min-height:38px}
  .row{display:flex;gap:8px;align-items:center}
  .grow{flex:1;min-width:0}
  .ellipsis{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  input{font:inherit;color:var(--fg);background:var(--panel2);border:1px solid var(--border);
        border-radius:10px;padding:12px;width:100%;min-height:44px}
  ul{list-style:none;margin:0;padding:0}
  li{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid var(--border)}
  li:last-child{border-bottom:none}
  li.current{background:rgba(106,169,255,.10);border-radius:8px}
  .idx{width:26px;text-align:center;color:var(--dim);font-variant-numeric:tabular-nums;font-size:13px}
  .t{font-size:15px}
  .a{font-size:13px;color:var(--dim)}
  .sect{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);margin:0 0 10px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--danger);flex:none}
  .dot.on{background:#38d39f}
  #setup{display:none}
  .hint{font-size:13px;color:var(--dim);margin-top:8px}
</style>
</head>
<body>
<header>
  <div class="row">
    <span class="dot" id="dot"></span>
    <h1 class="grow">Karaoke Remote</h1>
    <button id="forget" style="padding:6px 10px;min-height:32px;font-size:13px">Unpair</button>
  </div>
</header>
<main>

<div id="setup" class="card">
  <p class="sect">Pair this phone</p>
  <p class="muted" style="margin-top:0">Enter the code shown in the desktop player.</p>
  <input id="token" placeholder="pairing code" autocomplete="off"
         autocapitalize="off" autocorrect="off" spellcheck="false">
  <div class="hint" id="err"></div>
  <button class="primary" id="pair" style="width:100%;margin-top:12px">Connect</button>
</div>

<div id="app" style="display:none">
  <div class="card">
    <p class="sect">Now playing</p>
    <div id="now"><p class="muted" style="margin:0">Nothing playing</p></div>
    <div class="row" style="margin-top:14px">
      <button class="primary grow" id="next">⏭ Skip to next</button>
    </div>
    <p class="hint">Playback is controlled on the PC. This remote can queue and skip.</p>
  </div>

  <div class="card">
    <p class="sect">Add a song</p>
    <input id="q" placeholder="Search by title or artist" autocomplete="off">
    <ul id="results" style="margin-top:6px"></ul>
  </div>

  <div class="card">
    <div class="row" style="margin-bottom:10px">
      <p class="sect grow" style="margin:0">Queue (<span id="qcount">0</span>)</p>
      <button class="danger" id="clear">Clear all</button>
    </div>
    <ul id="queue"></ul>
  </div>
</div>

</main>
<script>
(function(){
  var $=function(id){return document.getElementById(id)}
  var token=localStorage.getItem('remoteToken')||''
  var es=null

  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}

  function api(path,opts){
    opts=opts||{}
    opts.headers=Object.assign({'X-Remote-Token':token},opts.headers||{})
    return fetch(path,opts).then(function(r){
      if(r.status===401){unpair('Pairing code rejected.');throw new Error('unauthorized')}
      return r
    })
  }

  function post(path,body){
    return api(path,{method:'POST',headers:{'Content-Type':'application/json'},
                     body:JSON.stringify(body||{})})
  }

  function setOnline(on){$('dot').className='dot'+(on?' on':'')}

  function unpair(msg){
    if(es){es.close();es=null}
    token='';localStorage.removeItem('remoteToken')
    $('app').style.display='none';$('setup').style.display='block'
    $('err').textContent=msg||'';setOnline(false)
  }

  function render(s){
    var now=$('now')
    if(s.playing){
      now.innerHTML='<div class="now-title ellipsis">'+esc(s.playing.title)+'</div>'+
                    '<div class="now-artist ellipsis">'+esc(s.playing.artist||'')+'</div>'+
                    '<div class="muted" style="font-size:13px;margin-top:6px">'+esc(s.status)+'</div>'
    } else {
      now.innerHTML='<p class="muted" style="margin:0">Nothing playing</p>'
    }
    $('qcount').textContent=s.queue.length
    var q=$('queue')
    if(!s.queue.length){q.innerHTML='<li class="muted">Queue is empty</li>';return}
    q.innerHTML=s.queue.map(function(it,i){
      return '<li>'+
        '<span class="idx">'+(i+1)+'</span>'+
        '<span class="grow" style="min-width:0">'+
          '<div class="t ellipsis">'+esc(it.title)+'</div>'+
          '<div class="a ellipsis">'+esc(it.artist||'')+'</div>'+
        '</span>'+
        '<button class="danger" data-rm="'+i+'">Remove</button></li>'
    }).join('')
  }

  function connect(){
    if(es)es.close()
    es=new EventSource('/api/events?token='+encodeURIComponent(token))
    es.onmessage=function(e){setOnline(true);render(JSON.parse(e.data))}
    es.onerror=function(){setOnline(false)}
  }

  function start(){
    $('setup').style.display='none';$('app').style.display='block'
    connect()
  }

  $('pair').onclick=function(){
    var v=$('token').value.trim()
    if(!v)return
    token=v
    api('/api/state').then(function(r){
      if(!r.ok)throw new Error('bad')
      localStorage.setItem('remoteToken',token)
      $('err').textContent=''
      start()
    }).catch(function(){$('err').textContent='Could not connect. Check the code.'})
  }
  $('token').addEventListener('keydown',function(e){if(e.key==='Enter')$('pair').click()})
  $('forget').onclick=function(){unpair('')}
  $('next').onclick=function(){post('/api/next')}
  $('clear').onclick=function(){if(confirm('Clear the whole queue?'))post('/api/queue/clear')}

  $('queue').onclick=function(e){
    var b=e.target.closest('button[data-rm]')
    if(b)post('/api/queue/remove',{index:Number(b.dataset.rm)})
  }
  $('results').onclick=function(e){
    var b=e.target.closest('button[data-add]')
    if(!b)return
    post('/api/queue/add',{songId:b.dataset.add})
    b.textContent='Added'
    setTimeout(function(){b.textContent='Add'},900)
  }

  var timer=null
  $('q').addEventListener('input',function(){
    clearTimeout(timer)
    var v=$('q').value.trim()
    timer=setTimeout(function(){
      if(!v){$('results').innerHTML='';return}
      api('/api/search?q='+encodeURIComponent(v)).then(function(r){return r.json()})
        .then(function(d){
          var items=(d&&d.items)||[]
          if(!items.length){$('results').innerHTML='<li class="muted">No matches</li>';return}
          $('results').innerHTML=items.map(function(s){
            return '<li><span class="grow" style="min-width:0">'+
              '<div class="t ellipsis">'+esc(s.title)+'</div>'+
              '<div class="a ellipsis">'+esc(s.artist||'')+'</div></span>'+
              '<button data-add="'+esc(s.id)+'">Add</button></li>'
          }).join('')
        }).catch(function(){})
    },250)
  })

  if(token)start(); else $('setup').style.display='block'
})()
</script>
</body>
</html>`
}
