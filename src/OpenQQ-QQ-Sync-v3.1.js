// ==UserScript==
// @name         OpenQQ旧QQ完整数据迁移-多海豹使用
// @author       summer_pinellia@DNT
// @version      3.1
// @description  OpenQQ 与旧 QQ 数据迁移；多 SeaDice 实例；绑定旧QQ时通过 旧QQ@qq.com 邮箱验证码确认【请下载相应的openqq.exe和bridge-port.txt】
// @sealVersion  >=1.6.0
// ==/UserScript==
(() => {
  const EXT_NAME='openqq_qq_realtime_sync_v20';
  const KEY='bindings_v20';
  const PORT_KEY='bridge_port_last_v20';
  if(seal.ext.find(EXT_NAME)) return;
  const ext=seal.ext.new(EXT_NAME,'summer_pinellia@DNT','3.1');

  const getPort=()=>{
    try {
      if(seal.ext.getIntConfig) {
        const p=Number(seal.ext.getIntConfig(ext,'bridge_port'));
        if(Number.isInteger(p)&&p>=1&&p<=65535) return p;
      }
    } catch(_) {}
    return 38999;
  };
  const getHost=()=>{
    try {
      const h=(String(seal.ext.getStringConfig(ext,'bridge_host')||'').trim())||'127.0.0.1';
      return h;
    } catch(_) { return '127.0.0.1'; }
  };
  const getToken=()=>{
    try { return String(seal.ext.getStringConfig(ext,'bridge_token')||'').trim(); } catch(_) { return ''; }
  };
  const withToken=p=>{
    const t=getToken();
    if(!t) return p;
    return p+(p.includes('?')?'&':'?')+'token='+encodeURIComponent(t);
  };
  const bridge=()=>`http://${getHost()}:${getPort()}`;
  const lastPort=()=>{try{const n=Number(ext.storageGet(PORT_KEY)||0);return Number.isInteger(n)&&n>=1&&n<=65535?n:0}catch(_){return 0}};
  const saveLastPort=p=>{try{ext.storageSet(PORT_KEY,String(p))}catch(_) {}};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));

  async function syncPortToBridge(){
    const p=getPort();
    const candidates=[p,lastPort(),38999].filter((v,i,a)=>v&&a.indexOf(v)===i);
    for(const old of candidates){
      try{
        const r=await fetch(withToken(`http://${getHost()}:${old}/set-port?port=${encodeURIComponent(p)}`));
        if(r.ok){saveLastPort(p); if(old!==p) await sleep(600); return true;}
      }catch(_){}
    }
    saveLastPort(p);
    return false;
  }

  const getB=()=>{try{return JSON.parse(ext.storageGet(KEY)||'{}')}catch(_){return {}}};
  const saveB=x=>ext.storageSet(KEY,JSON.stringify(x));
  const uid=c=>String(c?.player?.userId||'');
  const gid=c=>String(c?.group?.groupId||c?.group?.id||'');
  const reply=(ctx,msg,text)=>{try{seal.replyToSender(ctx,msg,String(text).slice(0,2000))}catch(_) {}};

  function cfgString(key, fallback=''){
    try { return String(seal.ext.getStringConfig(ext,key)||fallback).trim(); } catch(_) { return fallback; }
  }
  function smtpConfig(){
    return {
      sender_email: cfgString('sender_email',''),
      smtp_password: cfgString('smtp_password',''),
      smtp_host: cfgString('smtp_host','smtp.qq.com'),
      smtp_port: Number(seal.ext.getIntConfig(ext,'smtp_port')||465),
      smtp_ssl: true,
    };
  }

  async function postJson(path, body){
    let r;
    try {
      r=await fetch(withToken(bridge()+path),{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body||{})
      });
    } catch(e){ throw new Error(`无法连接同步桥 ${bridge()}：${e?.message||e}`); }
    const text=await r.text();
    let data={};
    try{data=JSON.parse(text||'{}')}catch(_){}
    if(!r.ok) throw new Error(data?.error||text||`bridge http ${r.status}`);
    if(data?.ok===false) throw new Error(data?.error||'同步桥返回失败');
    return data;
  }

  async function syncEmailConfig(){
    const c=smtpConfig();
    if(!c.sender_email) throw new Error('请先在插件配置中填写发件邮箱。');
    if(!c.smtp_password) throw new Error('请先在插件配置中填写SMTP授权码。');
    if(!/^\S+@\S+\.\S+$/.test(c.sender_email)) throw new Error('发件邮箱格式不正确。');
    if(!Number.isInteger(c.smtp_port)||c.smtp_port<1||c.smtp_port>65535) throw new Error('SMTP端口配置不正确。');
    await postJson('/set-email-config',c);
  }

  async function api(path,p){
    const q=Object.keys(p||{}).map(k=>encodeURIComponent(k)+'='+encodeURIComponent(String(p[k]))).join('&');
    let r;
    try { r=await fetch(withToken(bridge()+path+(q?'?'+q:''))); }
    catch(e){ throw new Error(`无法连接同步桥 ${bridge()}：${e?.message||e}`); }
    const text=await r.text();
    let body={}; try { body=JSON.parse(text||'{}'); } catch(_) {}
    if(!r.ok) throw new Error(body?.error||text||`bridge http ${r.status}`);
    if(body?.ok===false) throw new Error(body?.error||'同步桥返回失败');
    return body;
  }

  function cmd(name,help,fn){
    const c=seal.ext.newCmdItemInfo(); c.name=name; c.help=help;
    c.solve=(ctx,msg,args)=>{
      fn(ctx,msg,args).catch(e=>{
        const reason=String(e?.message||e||'未知错误').replace(/^Error:\s*/,'').trim();
        reply(ctx,msg,`同步失败：${reason||'未知错误'}`);
      });
      return seal.ext.newCmdExecuteResult(true);
    };
    ext.cmdMap[name]=c;
  }

  const keyFor=c=>uid(c)+'|'+gid(c);
  const summary=r=>{
    const chars=Array.isArray(r?.characters)?r.characters:[];
    const names=chars.map(x=>typeof x==='string'?x:(x?.name||x?.title||x?.id||'')).filter(Boolean);
    let s=`同步完成！\n\n角色卡：${Number(r?.character_count??names.length)} 张`;
    if(names.length) s+='\n'+names.map(n=>`- ${n}`).join('\n');
    s+=`\n\n群属性：${Number(r?.group_attr_count||0)} 条`;
    if(r?.log_error){
      s+=`\nLog：迁移失败`;
      s+=`\nLog记录：未迁移`;
      s+=`\n原因：${String(r.log_error)}`;
    }else{
      s+=`\nLog：${Number(r?.log_count||0)} 个`;
      s+=`\nLog记录：${Number(r?.log_item_count||0)} 条`;
    }
    if(Array.isArray(r?.skipped_empty_characters)&&r.skipped_empty_characters.length)
      s+=`\n\n跳过空角色卡：${r.skipped_empty_characters.length} 张`;
    if(Number(r?.log_skipped||0)>0)
      s+=`\n\n识别为已迁移、未重复复制：${Number(r.log_skipped)} 个`;
    if(Number(r?.log_failed||0)>0){
      s+=`\n\nLog迁移失败：${Number(r.log_failed)} 个（其余已照常迁移）`;
      const errs=Array.isArray(r?.log_errors)?r.log_errors:[];
      if(errs.length) s+='\n'+errs.slice(0,10).map(e=>`- ${e}`).join('\n');
      s+='\n详细原因已写入同步桥目录的 bridge_error.log。';
    }
    return s;
  };

  async function verifyBindCode(ctx,msg,code){
    await syncPortToBridge();
    await syncEmailConfig();
    const current=uid(ctx),group=gid(ctx);
    if(!current)return reply(ctx,msg,'无法读取用户ID。');
    if(!group)return reply(ctx,msg,'请在目标群执行。');
    const p=ext.storageGet('pending_bind_v20');
    let x=null; try{x=JSON.parse(p||'null')}catch(_){}
    if(!x || !x.oldQQ || !x.oldGroup) return reply(ctx,msg,'没有待验证的绑定请求，请先执行 .旧QQ绑定 <旧QQ> <旧群>。');
    if(x.current!==current || x.group!==group) return reply(ctx,msg,'当前账号或群与待验证请求不一致，请重新执行 .旧QQ绑定。');
    const r=await api('/verify-code',{old:x.oldQQ,current,group,oldGroup:x.oldGroup,code});
    const b=getB(),k=keyFor(ctx);
    b[k]={oldQQ:x.oldQQ,oldGroup:String(x.oldGroup),current,group,updatedAt:Date.now()}; saveB(b);
    ext.storageSet('pending_bind_v20','');
    reply(ctx,msg,summary(r));
  }

  async function bind(ctx,msg,old,oldGroup){
    await syncPortToBridge();
    const current=uid(ctx),group=gid(ctx);
    if(!current)return reply(ctx,msg,'无法读取用户ID。');
    if(!group)return reply(ctx,msg,'请在目标群执行。');
    const r=await api('/verify-code',{old,current,group,oldGroup,code:'__already_verified__'});
    reply(ctx,msg,summary(r));
  }

  cmd('旧QQ桥状态','检查同步桥',async(ctx,msg)=>{
    await syncPortToBridge();
    const r=await api('/health',{});
    reply(ctx,msg,r?.ok?`桥正常。\n端口：${r.port}\n版本：${r.version}`:'桥异常。');
  });

  cmd('旧QQ邮箱测试','测试发件邮箱：向配置中的发件邮箱发送测试邮件',async(ctx,msg)=>{
    await syncPortToBridge();
    await syncEmailConfig();
    const r=await postJson('/email-test',{});
    reply(ctx,msg,`测试邮件已发送至：${r.email}\n请检查收件箱（以及垃圾邮件）。`);
  });

  cmd('旧QQ绑定','申请旧QQ数据迁移验证码：.旧QQ绑定 <旧QQ> <旧群>',async(ctx,msg,args)=>{
    const old=args.getArgN(1).trim().replace(/^QQ:/i,'');
    const oldGroup=args.getArgN(2).trim().replace(/^QQ-Group:/i,'');
    if(!/^\d{5,20}$/.test(old)||!/^[0-9]{1,20}$/.test(oldGroup))return reply(ctx,msg,'格式错误。');
    const current=uid(ctx),group=gid(ctx);
    if(!current)return reply(ctx,msg,'无法读取用户ID。');
    if(!group)return reply(ctx,msg,'请在目标群执行。');
    await syncPortToBridge();
    await syncEmailConfig();
    const r=await api('/request-code',{old,current,group,oldGroup});
    ext.storageSet('pending_bind_v20',JSON.stringify({oldQQ:old,oldGroup:String(oldGroup),current,group,createdAt:Date.now()}));
    reply(ctx,msg,`验证邮件已发送至：${r.email}\n验证码有效期：5分钟。\n请在收到邮件后输入：.旧QQ验证码 <6位验证码>`);
  });

  cmd('旧QQ验证码','验证邮箱验证码并完成绑定：.旧QQ验证码 <6位验证码>',async(ctx,msg,args)=>{
    const code=args.getArgN(1).trim();
    if(!/^\d{6}$/.test(code))return reply(ctx,msg,'验证码应为6位数字。');
    await verifyBindCode(ctx,msg,code);
  });

  cmd('旧QQ同步','继续同步',async(ctx,msg)=>{
    const x=getB()[keyFor(ctx)];
    if(!x)return reply(ctx,msg,'请先绑定。');
    reply(ctx,msg,'当前版本绑定完成后会立即完成迁移，无需再次执行同步。');
  });

  cmd('旧QQ绑定信息','查看绑定',async(ctx,msg)=>{
    const x=getB()[keyFor(ctx)];
    reply(ctx,msg,x?`已绑定：QQ ${x.oldQQ} / 群 ${x.oldGroup}`:'未绑定。');
  });
  cmd('旧QQ角色','查看角色',async(ctx,msg,args)=>{
    let old=args.getArgN(1).trim().replace(/^QQ:/i,'');
    if(!old){const x=getB()[keyFor(ctx)];old=x?.oldQQ||'';}
    if(!/^\d{5,20}$/.test(old))return reply(ctx,msg,'请先绑定。');
    const r=await api('/lookup',{old});
    const chars=Array.isArray(r.characters)?r.characters:[];
    if(!chars.length)return reply(ctx,msg,'没有角色卡。');
    reply(ctx,msg,'角色卡：\n'+chars.map(x=>`- ${x.name||x.id}`).join('\n'));
  });
  cmd('旧QQ解绑','解除绑定',async(ctx,msg)=>{
    const b=getB(),k=keyFor(ctx);
    if(!b[k])return reply(ctx,msg,'未绑定。');
    delete b[k];saveB(b);reply(ctx,msg,'已解绑。');
  });

  cmd('旧QQ同步状态','查看自动同步是否开启、上次跑的时间和结果',async(ctx,msg)=>{
    await syncPortToBridge();
    const r=await api('/sync-status',{});
    const ps=Array.isArray(r?.pairs)?r.pairs:[];
    if(!ps.length)return reply(ctx,msg,'还没有任何同步关系。绑定成功后会【自动开启】定时同步。');
    const cur=uid(ctx),grp=gid(ctx);
    const mine=ps.filter(p=>p.current===cur&&p.group===grp);
    const show=mine.length?mine:ps;
    let s=mine.length?'本群的同步：':'全部同步关系（'+ps.length+' 条）：';
    for(const p of show){
      const ago=p.last_run?Math.round((Date.now()/1000-p.last_run)/60)+' 分钟前':'还没跑过';
      s+=`\n\n旧QQ ${p.old} / 群 ${p.old_group}`;
      s+=`\n  状态：${p.enabled?'开启':'已关闭'}`;
      s+=`\n  间隔：${Math.round((p.interval||600)/60)} 分钟`;
      s+=`\n  上次：${ago}`;
      const lr=p.last_result;
      if(lr){
        if(lr.ok===false){ s+=`\n  结果：失败 ${String(lr.error||'')}`; }
        else{
          const f=lr.logs?.forward||{}, b=lr.logs?.backward||{};
          s+=`\n  结果：旧→新 +${(f.new_logs||0)+(f.appended_logs||0)} 篇/+${f.items||0} 条`;
          s+=`\n        新→旧 +${(b.new_logs||0)+(b.appended_logs||0)} 篇/+${b.items||0} 条`;
          if(lr.cards_added) s+=`\n        角色卡 +${lr.cards_added}`;
          if(lr.pc?.action&&lr.pc.action!=='none') s+=`\n        PC：${lr.pc.action}`;
        }
      }
    }
    reply(ctx,msg,s);
  });

  cmd('旧QQ立刻同步','马上跑一次本群的增量同步，不用等定时器',async(ctx,msg)=>{
    await syncPortToBridge();
    const cur=uid(ctx),grp=gid(ctx);
    if(!cur||!grp)return reply(ctx,msg,'请在群里执行。');
    const r=await api('/sync-now',{current:cur,group:grp});
    const one=Array.isArray(r?.results)?(r.results[0]||{}):r;
    if(one.ok===false)return reply(ctx,msg,`同步失败：${one.error||'未知错误'}`);
    if(one.ok===undefined&&!one.logs)return reply(ctx,msg,'本群还没有同步关系。先执行 .旧QQ绑定。');
    const f=one.logs?.forward||{}, b=one.logs?.backward||{};
    let s='同步完成！';
    s+=`\n\n旧→新：+${(f.new_logs||0)+(f.appended_logs||0)} 篇 / +${f.items||0} 条`;
    s+=`\n新→旧：+${(b.new_logs||0)+(b.appended_logs||0)} 篇 / +${b.items||0} 条`;
    if(one.cards_added) s+=`\n角色卡：+${one.cards_added} 张`;
    if(one.pc?.action==='updated') s+=`\nPC 数据：已回写到旧QQ`;
    else if(one.pc?.action==='created') s+=`\nPC 数据：已在旧QQ侧建立`;
    else if(one.pc?.action==='skipped_older') s+=`\nPC 数据：旧QQ 那份更新，未覆盖`;
    reply(ctx,msg,s);
  });

  cmd('旧QQ同步开关','开启或关闭本群的自动同步：.旧QQ同步开关 开 / 关',async(ctx,msg,args)=>{
    await syncPortToBridge();
    const v=args.getArgN(1).trim();
    if(!['开','关','on','off'].includes(v))return reply(ctx,msg,'用法：.旧QQ同步开关 开 或 .旧QQ同步开关 关');
    const on=['开','on'].includes(v);
    const cur=uid(ctx),grp=gid(ctx);
    if(!cur||!grp)return reply(ctx,msg,'请在群里执行。');
    const r=await api('/sync-enable',{current:cur,group:grp,on:on?'1':'0'});
    reply(ctx,msg,`本群自动同步已${r?.enabled?'开启':'关闭'}。`);
  });

  seal.ext.register(ext);
  seal.ext.registerIntConfig(ext, 'bridge_port', 38999, 'Bridge端口', '同步桥设置');
  seal.ext.registerStringConfig(ext, 'bridge_host', '127.0.0.1', 'Bridge主机（Docker/远程时填写）', '同步桥设置');
  seal.ext.registerStringConfig(ext, 'bridge_token', '', 'Bridge访问令牌（设置了才填）', '同步桥设置');
  seal.ext.registerStringConfig(ext, 'sender_email', '', '发件邮箱', '邮箱验证设置');
  seal.ext.registerStringConfig(ext, 'smtp_password', '', 'SMTP授权码', '邮箱验证设置');
  seal.ext.registerStringConfig(ext, 'smtp_host', 'smtp.qq.com', 'SMTP服务器', '邮箱验证设置');
  seal.ext.registerIntConfig(ext, 'smtp_port', 465, 'SMTP端口', '邮箱验证设置');
})();
