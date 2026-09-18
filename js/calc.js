
/* 공통 금액/시뮬레이션 함수 — 금액 단위는 모두 '만원' */
(function(){
  function won(v){
    if(v===null||v===undefined||!isFinite(v)) return '-';
    var neg=v<0; v=Math.round(Math.abs(v));
    var s;
    if(v>=10000){ var e=Math.floor(v/10000), m=v%10000;
      s=e+'억'+(m?' '+m.toLocaleString()+'만원':'원'); }
    else s=v.toLocaleString()+'만원';
    return (neg?'-':'')+s;
  }
  function n1(v){ return (Math.round(v*10)/10).toLocaleString(undefined,{minimumFractionDigits:0,maximumFractionDigits:1}); }
  function mrate(annualPct){ return Math.pow(1+annualPct/100,1/12)-1; }

  /* 목표 금액: 오늘 기준 결혼비용 x 내 비율, 물가상승률만큼 매년 커짐 */
  function targetAt(age,o){
    var base=o.weddingCost*(o.share/100);
    return base*Math.pow(1+o.infl/100, Math.max(0,age-o.nowAge));
  }

  /* 실제로 결혼하게 될 나이 시뮬레이션 (월 복리) */
  function simulate(o){
    o=Object.assign({nowAge:15,infl:0,share:100,maxAge:120},o);
    var m=mrate(o.rate), assets=o.preSave, age=o.jobAge, months=0;
    if(assets>=targetAt(age,o)) return {age:age,months:0,assets:assets,target:targetAt(age,o),ok:true};
    var lim=(o.maxAge-o.jobAge)*12;
    while(months<lim){
      assets=assets*(1+m)+o.monthlySave; months++;
      age=o.jobAge+months/12;
      var tg=targetAt(age,o);
      if(assets>=tg) return {age:age,months:months,assets:assets,target:tg,ok:true};
    }
    return {age:null,months:null,assets:assets,target:targetAt(o.maxAge,o),ok:false};
  }

  /* 희망 나이에 맞추려면 매달 얼마를 넣어야 하는가 */
  function needMonthly(o){
    var n=Math.round((o.wishAge-o.jobAge)*12);
    if(n<=0) return null;
    var m=mrate(o.rate), tg=targetAt(o.wishAge,o);
    var fvPre=o.preSave*Math.pow(1+m,n);
    var fac=(m===0)?n:(Math.pow(1+m,n)-1)/m;
    return Math.max(0,(tg-fvPre)/fac);
  }

  /* 희망 나이에 맞추려면 수익률이 몇 %여야 하는가 (이분탐색, 0~60%) */
  function needRate(o){
    var lo=0,hi=60,f=function(r){
      var s=Object.assign({},o,{rate:r});
      var n=Math.round((o.wishAge-o.jobAge)*12);
      if(n<=0) return -1;
      var m=mrate(r), fac=(m===0)?n:(Math.pow(1+m,n)-1)/m;
      return o.preSave*Math.pow(1+m,n)+o.monthlySave*fac-targetAt(o.wishAge,o);
    };
    if(f(hi)<0) return null;
    for(var i=0;i<60;i++){ var mid=(lo+hi)/2; if(f(mid)<0) lo=mid; else hi=mid; }
    return hi;
  }
  function ageText(a){ if(a===null) return '평생 모으기 어려움'; return n1(a)+'세'; }
  window.CALC={won:won,n1:n1,simulate:simulate,needMonthly:needMonthly,needRate:needRate,
               targetAt:targetAt,ageText:ageText};
})();
