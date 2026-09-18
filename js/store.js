
/* 학생 입력 자동 저장 (이 기기의 브라우저에만 저장됩니다) */
(function(){
  var KEY='wedding-project-v2';
  var data={};
  try{ data=JSON.parse(localStorage.getItem(KEY)||'{}')||{}; }catch(e){ data={}; }

  var S={
    all:function(){return data;},
    get:function(k,dv){ var v=data[k]; return (v===undefined||v===null||v==='')?(dv===undefined?'':dv):v; },
    num:function(k,dv){ var v=parseFloat(data[k]); return isFinite(v)?v:(dv===undefined?null:dv); },
    has:function(k){ var v=data[k]; return !(v===undefined||v===null||v===''); },
    set:function(k,v){ data[k]=v; S.save(); },
    save:function(){ try{ localStorage.setItem(KEY,JSON.stringify(data)); }catch(e){} },
    clearLesson:function(p){ Object.keys(data).forEach(function(k){ if(k.indexOf(p)===0) delete data[k]; }); S.save(); },
    /* data-store 속성이 붙은 입력칸을 자동 저장/복원 */
    bind:function(root){
      root=root||document;
      var els=root.querySelectorAll('[data-store]');
      for(var i=0;i<els.length;i++){
        (function(el){
          var k=el.getAttribute('data-store');
          if(S.has(k)) el.value=data[k];
          else if(el.value!=='') data[k]=el.value;
          var ev=(el.tagName==='SELECT')?'change':'input';
          el.addEventListener(ev,function(){ data[k]=el.value; S.save(); flash(); });
        })(els[i]);
      }
      S.save();
    },
    progress:function(keys){
      var n=0; for(var i=0;i<keys.length;i++) if(S.has(keys[i])) n++;
      return {done:n,total:keys.length,pct:keys.length?Math.round(n/keys.length*100):0};
    },
    exportFile:function(){
      var blob=new Blob([JSON.stringify(data,null,1)],{type:'application/json'});
      var a=document.createElement('a');
      var nm=(S.get('name')||'학생')+'_금융프로젝트.json';
      a.href=URL.createObjectURL(blob); a.download=nm; a.click();
    },
    importFile:function(file,cb){
      var r=new FileReader();
      r.onload=function(){ try{ var o=JSON.parse(r.result);
        Object.keys(o).forEach(function(k){ data[k]=o[k]; }); S.save(); cb&&cb(true);
      }catch(e){ cb&&cb(false); } };
      r.readAsText(file);
    }
  };
  var tmr=null;
  function flash(){
    var el=document.getElementById('savedFlag'); if(!el) return;
    el.textContent='저장됨'; el.className='saved';
    clearTimeout(tmr); tmr=setTimeout(function(){ el.textContent=''; },1200);
  }
  S.KEYS={
    l1:['l1_job','l1_major','l1_salary','l1_satisf','l1_reason','l1_jobAge','l1_preSave',
        'l1_monthlyPay','l1_monthlySave','l1_wishAge','l1_weddingCost','l1_share','l1_memo'],
    l2:['l2_infl','l2_s1_rate','l2_s1_save','l2_s2_rate','l2_s2_save','l2_s3_rate','l2_s3_save',
        'l2_pick','l2_adj_jobAge','l2_adj_preSave','l2_adj_monthlyPay','l2_adj_monthlySave',
        'l2_adj_wishAge','l2_adj_weddingCost','l2_adj_share','l2_adj_rate','l2_adj_plan'],
    l3:['l3_memo'],l4:['l4_memo'],l5:['l5_memo']
  };
  window.STORE=S;
})();
