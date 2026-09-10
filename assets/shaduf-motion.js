/* The lever, rope and bucket share one clock, so the mechanism stays connected. */
window.ShadufMotion = (() => {
  let frame=0,playingOnce=null;
  const clamp = x => Math.max(0,Math.min(1,x));
  const ease = x => {x=clamp(x);return x*x*(3-2*x);};
  const mix = (a,b,t) => a+(b-a)*t;
  function animate({slow=false,reduced=false,once=false,complete=()=>{}}={}) {
    cancelAnimationFrame(frame);
    const root=document.querySelector('.shaduf-mechanism');
    if(!root){complete();return;}
    const get=s=>root.querySelector(s);
    const arm=get('.shaduf-arm'),rope=get('.shaduf-rope'),bucket=get('.shaduf-bucket');
    const weight=get('.shaduf-counterweight'),weightRope=get('.shaduf-weight-rope');
    const water=get('.shaduf-bucket-water'),pour=get('.shaduf-pour'),ripple=get('.shaduf-ripple');
    const reel=get('.shaduf-word-reel'),drops=[...root.querySelectorAll('.shaduf-droplets circle')];
    const begun=performance.now(),duration=slow?4500:1800;
    function draw(now) {
      const elapsed=now-begun;
      const t=reduced ? .43 : once ? Math.min(elapsed/duration,1) : (elapsed%duration)/duration;
      let angle=26,tilt=0,fill=0;
      if(t<.16)fill=ease(t/.16);
      else if(t<.46){angle=mix(26,-27,ease((t-.16)/.3));fill=1;}
      else if(t<.64){angle=-27;tilt=58*ease((t-.46)/.1);fill=1-ease((t-.5)/.14);}
      else if(t<.74){angle=-27;tilt=58*(1-ease((t-.64)/.1));}
      else angle=mix(-27,26,ease((t-.74)/.26));
      const rad=angle*Math.PI/180;
      const x=175+148*Math.cos(rad),y=95+148*Math.sin(rad),bucketY=y+63;
      const wx=175-88*Math.cos(rad),wy=95-88*Math.sin(rad);
      arm.setAttribute('transform',`rotate(${angle} 175 95)`);
      rope.setAttribute('d',`M${x} ${y}V${bucketY-15}`);
      bucket.setAttribute('transform',`translate(${x} ${bucketY}) rotate(${tilt} 0 -15)`);
      weight.setAttribute('transform',`translate(${wx} ${wy+12})`);
      weightRope.setAttribute('d',`M${wx} ${wy}v12`);
      water.setAttribute('y',27-22*fill);
      const flow=ease((t-.51)/.04)*(1-ease((t-.62)/.05));
      const tip=tilt*Math.PI/180;
      const outletX=x+16*Math.cos(tip)-15*Math.sin(tip),outletY=bucketY-15+16*Math.sin(tip)+15*Math.cos(tip);
      pour.setAttribute('d',`M${outletX} ${outletY}Q${outletX+28} ${outletY+4} 352 167`);
      pour.style.opacity=flow;
      pour.style.strokeDashoffset=-(now-begun)/30;
      drops.forEach((d,i)=>{const f=(((now-begun)/230+i*.33)%1);d.setAttribute('cx',352+Math.sin(i*2+f*5)*10);d.setAttribute('cy',168-Math.sin(f*Math.PI)*12);d.style.opacity=flow*(1-f);});
      ripple.style.opacity=t<.2?Math.sin(t/.2*Math.PI)*.7:.1;
      const rolling=t<.22?0:t<.4?ease((t-.22)/.18):t<.5?1:t<.65?1+ease((t-.5)/.15):t<.83?2:2+ease((t-.83)/.17);
      reel.style.transform=`translateY(${-rolling*24}px)`;
      reel.style.filter=`blur(${Math.abs(Math.sin(rolling*Math.PI))*.7}px)`;
      root.dataset.phase=t<.22?'gather':t<.5?'lift':t<.74?'pour':'return';
      if(once&&(reduced||elapsed>=duration)){frame=0;complete();return;}
      if(!reduced)frame=requestAnimationFrame(draw);
    }
    draw(begun);
  }
  function start(options){if(!playingOnce)animate(options);}
  function stop(){if(playingOnce)return;cancelAnimationFrame(frame);frame=0;}
  function playOnce(options={}){
    if(playingOnce)return playingOnce;
    let finish;
    const result=new Promise(resolve=>{finish=resolve;});playingOnce=result;
    animate({...options,once:true,complete:()=>{playingOnce=null;finish();}});
    return result;
  }
  return {start,stop,playOnce};
})();
