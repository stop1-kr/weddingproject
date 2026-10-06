
/* 3차시 투자 결과 계산 + 간단한 SVG 그래프 (월말 종가 자료 기준) */
(function(){
  function mLabel(s){ return s.slice(0,4)+'년 '+parseInt(s.slice(5,7),10)+'월'; }
  function pct(v,d){
    d=(d===undefined)?1:d;
    var x=v*100, r=Math.round(Math.abs(x)*Math.pow(10,d));
    var s=(r/Math.pow(10,d)).toFixed(d);
    return (r>0?(x>0?'+':'\u2212'):'')+s+'%';
  }
  function pctAbs(v,d){ d=(d===undefined)?1:d; return (Math.round(Math.abs(v)*100*Math.pow(10,d))/Math.pow(10,d)).toFixed(d)+'%'; }

  /* c: {months:['2010-01',...], prices:[...]}, limitPct: 학생이 정한 최대 손실(%) 또는 null */
  function analyze(c,limitPct){
    var m=c.months, p=c.prices, n=p.length;
    if(!m||n<13) return null;
    var lastIdx={}, i;
    for(i=0;i<n;i++) lastIdx[m[i].slice(0,4)]=i;
    var ys=Object.keys(lastIdx).sort(), yr=[];
    ys.forEach(function(y,k){
      var end=lastIdx[y], base=(k===0)?0:lastIdx[ys[k-1]];
      if(end===base) return;
      yr.push({year:y,ret:p[end]/p[base]-1,partial:(k===0)||(m[end].slice(5,7)!=='12')});
    });
    var best=yr[0], worst=yr[0];
    yr.forEach(function(o){ if(o.ret>best.ret) best=o; if(o.ret<worst.ret) worst=o; });

    var peak=0, mdd=0, mp=0, mt=0, exit=null, dd=[];
    for(i=0;i<n;i++){
      if(p[i]>p[peak]) peak=i;
      var d=p[i]/p[peak]-1; dd.push(d);
      if(d<mdd){ mdd=d; mp=peak; mt=i; }
      if(exit===null && limitPct!==null && limitPct!==undefined && d<=-limitPct/100) exit=i;
    }
    var rec=null;
    for(i=mt+1;i<n;i++){ if(p[i]>=p[mp]){ rec=i; break; } }
    var years=(n-1)/12;
    var cagr=Math.pow(p[n-1]/p[0],1/years)-1;
    var hasLimit=(limitPct!==null&&limitPct!==undefined);
    return {
      n:n, first:m[0], last:m[n-1], years:years,
      yearly:yr, best:best, worst:worst,
      mdd:mdd, peakM:m[mp], troughM:m[mt], recoverM:(rec===null?null:m[rec]),
      recoverMonths:(rec===null?null:rec-mt),
      retAtTrough:p[mt]/p[0]-1,
      total:p[n-1]/p[0]-1, cagr:cagr,
      success:hasLimit?(-mdd*100<=limitPct+1e-9):null,
      exitM:(exit===null?null:m[exit]), exitRet:(exit===null?null:p[exit]/p[0]-1),
      dd:dd
    };
  }

  function monthRange(lists){
    var min=null,max=null;
    lists.forEach(function(a){
      if(!a.length) return;
      if(min===null||a[0]<min) min=a[0];
      if(max===null||a[a.length-1]>max) max=a[a.length-1];
    });
    var out=[]; if(min===null) return out;
    var y=parseInt(min.slice(0,4),10), mo=parseInt(min.slice(5,7),10);
    while(true){
      var s=y+'-'+(mo<10?'0':'')+mo;
      if(s>max) break;
      out.push(s); mo++; if(mo>12){ mo=1; y++; }
    }
    return out;
  }
  function align(months,all,values){
    var map={}, i, out=[];
    for(i=0;i<months.length;i++) map[months[i]]=values[i];
    for(i=0;i<all.length;i++) out.push(map.hasOwnProperty(all[i])?map[all[i]]:null);
    return out;
  }
  function niceStep(raw){
    var e=Math.pow(10,Math.floor(Math.log(raw)/Math.LN10)), f=raw/e;
    return (f<=1?1:f<=2?2:f<=5?5:10)*e;
  }
  /* o: {months, series:[{color,values}], yMin, yMax, hline:{value,label}, unit, height} */
  function lineChart(o){
    var W=720,H=o.height||250,L=56,R=16,T=12,B=28,n=o.months.length;
    var lo=Infinity,hi=-Infinity;
    o.series.forEach(function(s){ s.values.forEach(function(v){ if(v!==null){ if(v<lo) lo=v; if(v>hi) hi=v; } }); });
    if(o.hline){ lo=Math.min(lo,o.hline.value); hi=Math.max(hi,o.hline.value); }
    var pad=(hi-lo)*0.06||1;
    lo=(o.yMin!==undefined)?o.yMin:lo-pad;
    hi=(o.yMax!==undefined)?o.yMax:hi+pad;
    var step=niceStep((hi-lo)/4), t0=Math.ceil(lo/step-1e-9)*step;
    function X(i){ return L+(n<=1?0:i*(W-L-R)/(n-1)); }
    function Y(v){ return T+(hi-v)*(H-T-B)/(hi-lo); }
    var g='';
    for(var t=t0;t<=hi+1e-9;t+=step){
      var tv=Math.round(t*100)/100; if(tv===0) tv=0;
      g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(t).toFixed(1)+'" y2="'+Y(t).toFixed(1)+'" stroke="#e5e7eb"/>'
        +'<text x="'+(L-6)+'" y="'+(Y(t)+4).toFixed(1)+'" text-anchor="end" font-size="12" fill="#6b7280">'+tv.toLocaleString()+(o.unit||'')+'</text>';
    }
    var nYears=Math.max(1,Math.round(n/12)), every=Math.max(1,Math.ceil(nYears/8));
    for(var i=0;i<n;i++){
      var mm=o.months[i];
      if(mm.slice(5,7)==='01' && (parseInt(mm.slice(0,4),10)%every===0)){
        g+='<line x1="'+X(i).toFixed(1)+'" x2="'+X(i).toFixed(1)+'" y1="'+(H-B)+'" y2="'+(H-B+4)+'" stroke="#9ca3af"/>'
          +'<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" font-size="12" fill="#6b7280">'+mm.slice(0,4)+'</text>';
      }
    }
    if(o.hline){
      g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(o.hline.value).toFixed(1)+'" y2="'+Y(o.hline.value).toFixed(1)+'" stroke="#b91c1c" stroke-dasharray="6 4" stroke-width="1.5"/>'
        +'<text x="'+(W-R-4)+'" y="'+(Y(o.hline.value)-5).toFixed(1)+'" text-anchor="end" font-size="12" fill="#b91c1c">'+o.hline.label+'</text>';
    }
    o.series.forEach(function(s){
      var d='', open=false;
      s.values.forEach(function(v,k){
        if(v===null){ open=false; return; }
        d+=(open?'L':'M')+X(k).toFixed(1)+' '+Y(v).toFixed(1)+' '; open=true;
      });
      g+='<path d="'+d+'" fill="none" stroke="'+s.color+'" stroke-width="2" stroke-linejoin="round"/>';
    });
    return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" role="img" aria-label="'+(o.label||'그래프')+'" style="display:block">'+g+'</svg>';
  }

  window.INVEST={analyze:analyze,pct:pct,pctAbs:pctAbs,mLabel:mLabel,monthRange:monthRange,align:align,lineChart:lineChart};
  if(typeof module!=='undefined') module.exports=window.INVEST;
})();
