/* 4·5차시 공통 시장 자료 : 국내 주식 + 국내 ETF + 미국 주식·환율 (있는 것만)
   stocks-data.js / etf-data.js / us-data.js 를 읽어 window.MKT 로 내보냄 (페이지 맨 아래에서 불러올 것) */
(function(){
  function expand(D,key){
    if(!D||!D[key]) return {};
    Object.keys(D[key]).forEach(function(c){ var o=D[key][c];
      if(!o.months&&D.months){ o.prices=o.p; o.months=D.months.slice(o.s,o.s+o.p.length); } });
    return D[key];
  }
  var SD=window.STOCK_DATA||null, ED=window.ETF_DATA||null, UD=window.US_DATA||null;
  var ITEMS={}, RANK={}, URANK={};
  var stocks=expand(SD,'companies'), etfs=expand(ED,'etfs'), usd=expand(UD,'companies');
  Object.keys(stocks).forEach(function(c){ ITEMS['s'+c]={id:'s'+c,code:c,name:stocks[c].name,kind:'주식',cur:'KRW',months:stocks[c].months,prices:stocks[c].prices}; });
  Object.keys(etfs).forEach(function(c){ ITEMS['e'+c]={id:'e'+c,code:c,name:etfs[c].name,kind:'ETF',cur:'KRW',months:etfs[c].months,prices:etfs[c].prices}; });
  var UKIND={'주식':'미국주식','ETF':'미국ETF','코인':'코인','금':'금'};
  Object.keys(usd).forEach(function(t){ var o=usd[t]; ITEMS['u'+t]={id:'u'+t,code:t,name:o.name,kind:UKIND[o.kind]||'미국주식',cur:'USD',months:o.months,prices:o.prices}; });
  if(SD&&SD.ranking) SD.ranking.forEach(function(r){ RANK['s'+r.code]=r.rank; });
  if(UD&&UD.ranking) UD.ranking.forEach(function(r){ URANK['u'+r.code]=r.rank; });
  var IDS=Object.keys(ITEMS).filter(function(id){ return ITEMS[id].cur==='KRW'; });
  var UIDS=Object.keys(ITEMS).filter(function(id){ return ITEMS[id].cur==='USD'; });
  var HAS=IDS.length>0, HAS_ETF=Object.keys(etfs).length>0;
  var FX={}; if(UD&&UD.fx&&UD.months) UD.months.forEach(function(m,i){ if(UD.fx[i]) FX[m]=UD.fx[i]; });
  var HAS_US=UIDS.length>0&&Object.keys(FX).length>=12;
  var DSTART='2020-01', DEND='2026-09';
  IDS.forEach(function(id,i){ var m=ITEMS[id].months; if(!m||!m.length) return;
    if(i===0||m[0]<DSTART) DSTART=m[0]; if(i===0||m[m.length-1]>DEND) DEND=m[m.length-1]; });
  document.querySelectorAll('.startTxt').forEach(function(el){ el.textContent=INVEST.mLabel(DSTART); });
  document.querySelectorAll('.endTxt').forEach(function(el){ el.textContent=INVEST.mLabel(DEND); });
  /* 달러 종목을 원화로 바꾼 가격 (그 달 말 환율 × 달러 가격) */
  function krw(it){
    if(!it||it.cur!=='USD') return it;
    if(it._k) return it._k;
    var ms=[],ps=[]; it.months.forEach(function(m,i){ if(FX[m]){ ms.push(m); ps.push(it.prices[i]*FX[m]); } });
    it._k={id:it.id,code:it.code,name:it.name,kind:it.kind,cur:'KRW',months:ms,prices:ps}; return it._k;
  }

  /* 여러 종목의 공통 기간을 잘라 냄 */
  function common(list){
    var s=null,e=null;
    list.forEach(function(it){ var a=it.months[0], b=it.months[it.months.length-1]; if(s===null||a>s) s=a; if(e===null||b<e) e=b; });
    return {start:s,end:e};
  }
  function cut(it,s,e){
    var i0=it.months.indexOf(s), i1=it.months.indexOf(e);
    if(i0<0||i1<0) return null;
    return {months:it.months.slice(i0,i1+1),prices:it.prices.slice(i0,i1+1)};
  }
  /* 같은 금액씩 나눠 담은 그릇 (처음에 사고 계속 들고 있음) */
  function bowl(list,s,e){
    var parts=list.map(function(it){ return cut(it,s,e); }).filter(Boolean);
    if(!parts.length) return null;
    var n=parts[0].prices.length, out=[];
    for(var i=0;i<n;i++){ var t=0; parts.forEach(function(p){ t+=p.prices[i]/p.prices[0]; }); out.push(t/parts.length); }
    return {months:parts[0].months,prices:out};
  }
  function isFull(id){ var m=ITEMS[id].months; return m[0]===DSTART&&m[m.length-1]===DEND; }
  function fullItems(kind){ return IDS.filter(function(id){ return ITEMS[id].kind===kind&&isFull(id); }); }
  function topIds(){ return IDS.filter(function(id){ return RANK[id]; }).sort(function(a,b){ return RANK[a]-RANK[b]; }); }
  function norm(s){ return String(s||'').toLowerCase().replace(/\[[^\]]*\]/g,'').replace(/[\s()\-\.·&]/g,''); }
  var BYNAME={}; Object.keys(ITEMS).forEach(function(id){ var k=norm(ITEMS[id].name); if(!BYNAME[k]) BYNAME[k]=id; });
  function byName(nm){ return BYNAME[norm(nm)]||null; }
  var KTAG={'주식':'한국 주식','ETF':'한국 ETF','미국주식':'미국 주식','미국ETF':'미국 ETF','코인':'코인','금':'금','그릇':'직접 만든 그릇'};
  function label(it){ return it.name+(it.kind==='ETF'?' [ETF]':''); }
  function uLabel(it){ return it.name+(it.cur==='USD'&&it.kind!=='코인'&&it.kind!=='금'&&it.name.indexOf(it.code)<0?' ('+it.code+')':'')+' ['+KTAG[it.kind]+']'; }
  var COLORS=['#2563eb','#c2410c','#15803d','#7c3aed','#0891b2','#be185d'];
  /* 4차시 1단계 · 자료집 : 분야별 회사 목록 (이름이 자료에 있는 회사만 쓰임) */
  var SECTORS=[
    {n:'자동차',l:['현대차','기아','현대모비스','HL만도','한온시스템','현대위아','현대글로비스','에스엘','화신','서연이화']},
    {n:'건설',l:['현대건설','GS건설','대우건설','HDC현대산업개발','삼성E&A','삼성엔지니어링','계룡건설','동부건설','금호건설','KCC건설']},
    {n:'에너지·화학',l:['LG화학','SK이노베이션','S-Oil','롯데케미칼','한화솔루션','금호석유','금호석유화학','GS','SK가스','한국가스공사','한국전력']},
    {n:'금융',l:['KB금융','신한지주','하나금융지주','우리금융지주','기업은행','삼성생명','삼성화재','메리츠금융지주','DB손해보험','한국금융지주','BNK금융지주']},
    {n:'인터넷·게임',l:['NAVER','카카오','엔씨소프트','넷마블','펄어비스','위메이드','컴투스','네오위즈','NHN','더존비즈온']},
    {n:'음식료',l:['CJ제일제당','오리온','농심','삼양식품','롯데칠성','하이트진로','오뚜기','빙그레','동원F&B']},
    {n:'반도체',l:['삼성전자','SK하이닉스','한미반도체','DB하이텍','리노공업','원익IPS','이오테크닉스','하나마이크론','ISC','주성엔지니어링','솔브레인','동진쎄미켐']},
    {n:'바이오·제약',l:['삼성바이오로직스','셀트리온','유한양행','한미약품','알테오젠','HLB','녹십자','종근당','대웅제약']},
    {n:'조선·방산',l:['HD한국조선해양','삼성중공업','한화오션','한화에어로스페이스','LIG넥스원','현대로템','한국항공우주']},
    {n:'시가총액 TOP10',top:true}
  ];
  if(SD&&SD.all) SECTORS.push({n:'코스피·코스닥 전체',all:true});
  function secMembers(sec){
    if(sec.top) return topIds().filter(isFull);
    if(sec.all) return fullItems('주식');
    var out=[]; sec.l.forEach(function(nm){ var id=byName(nm); if(id&&ITEMS[id].kind==='주식'&&isFull(id)&&out.indexOf(id)<0) out.push(id); });
    return out;
  }
  function secStats(sec){
    var ids=secMembers(sec); if(ids.length<3) return {sec:sec,n:ids.length};
    var res=ids.map(function(id){ var it=ITEMS[id]; return {it:it,a:INVEST.analyze({months:it.months,prices:it.prices},null)}; });
    res.sort(function(x,y){ return y.a.total-x.a.total; });
    var b=bowl(ids.map(function(id){return ITEMS[id];}),DSTART,DEND), ba=INVEST.analyze(b,null);
    var avgMdd=res.reduce(function(t,r){return t+r.a.mdd;},0)/res.length;
    return {sec:sec,n:ids.length,res:res,best:res[0],worst:res[res.length-1],b:b,ba:ba,avgMdd:avgMdd,
      worstMdd:Math.min.apply(null,res.map(function(r){return r.a.mdd;})),below:res.filter(function(r){ return r.a.mdd<ba.mdd; }).length};
  }
  window.MKT={SD:SD,ED:ED,UD:UD,ITEMS:ITEMS,RANK:RANK,URANK:URANK,IDS:IDS,UIDS:UIDS,HAS:HAS,HAS_ETF:HAS_ETF,FX:FX,HAS_US:HAS_US,
    DSTART:DSTART,DEND:DEND,krw:krw,common:common,cut:cut,bowl:bowl,isFull:isFull,fullItems:fullItems,topIds:topIds,
    norm:norm,byName:byName,KTAG:KTAG,label:label,uLabel:uLabel,COLORS:COLORS,
    SECTORS:SECTORS,secMembers:secMembers,secStats:secStats};
})();
