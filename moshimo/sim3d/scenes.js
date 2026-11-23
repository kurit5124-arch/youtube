// もしもシリーズの3Dシミュレーション（three.js）。
// どの場面も t（秒）だけで絵が決まる（同じ t なら毎回同じ絵）ので、1コマずつ書き出せる。
//
// 場面:
//   earth : 自転する地球。昼と夜、夜側の街の明かり。params: hours（何時間ぶん回すか）, start_hour
//   room  : 眠らない人の部屋のタイムラプス。窓の外が昼→夜と変わり、時計が回る。
//           params: start_hour, hours, nod（居眠りでカクッとなる）, face（normal/tired）
//   brain : 脳。mode: clean（老廃物が流れ出る）/ dirty（たまっていく）
import * as THREE from './three.module.min.js';

const NOISE = /* glsl */`
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+10.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(0.5-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 105.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
float fbm(vec3 p){float f=0.0,a=0.5;for(int i=0;i<5;i++){f+=a*snoise(p);p*=2.03;a*=0.5;}return f;}
`;

// 決まった乱数（同じ seed なら同じ並び）
function rand(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

function starfield(n = 1500, r = 60) {
  const r_ = rand(7), pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const u = r_() * 2 - 1, th = r_() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    pos.set([r * s * Math.cos(th), r * u, r * s * Math.sin(th)], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  return new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 0.12, sizeAttenuation: true }));
}

// ------------------------------------------------------------------ 地球
function earth(p) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x02030a);
  const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.1, 200);
  scene.add(starfield());
  const sun = new THREE.Vector3(1, 0.25, 0.6).normalize();

  const mat = new THREE.ShaderMaterial({
    uniforms: { sunDir: { value: sun } },
    vertexShader: `varying vec3 vP; varying vec3 vN; varying vec3 vW;
      void main(){ vP=position; vN=normalize(mat3(modelMatrix)*normal);
        vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: NOISE + `uniform vec3 sunDir; varying vec3 vP; varying vec3 vN; varying vec3 vW;
      void main(){
        vec3 n=normalize(vN); float h=fbm(vP*1.7+vec3(3.1,1.7,0.4));
        float land=smoothstep(0.03,0.07,h);
        float lat=abs(normalize(vP).y);
        vec3 ocean=mix(vec3(0.01,0.06,0.20),vec3(0.03,0.22,0.45),smoothstep(-0.25,0.05,h));
        vec3 green=mix(vec3(0.10,0.34,0.12),vec3(0.50,0.42,0.24),smoothstep(0.55,0.95,snoise(vP*3.0)*0.5+0.5-lat*0.2));
        vec3 col=mix(ocean,green,land);
        col=mix(col,vec3(0.95),smoothstep(0.78,0.86,lat));
        float d=dot(n,sunDir); float day=smoothstep(-0.08,0.25,d);
        vec3 V=normalize(cameraPosition-vW); vec3 H=normalize(V+sunDir);
        float spec=pow(max(dot(n,H),0.0),60.0)*(1.0-land)*0.6;
        vec3 lit=col*(0.06+1.1*max(d,0.0))+spec*day;
        float city=land*(1.0-smoothstep(0.78,0.86,lat))*smoothstep(0.72,0.86,snoise(vP*48.0)*0.5+0.5+snoise(vP*6.0)*0.22);
        vec3 lights=vec3(1.0,0.75,0.35)*city*2.2*(1.0-day);
        float rim=pow(1.0-max(dot(n,V),0.0),3.0);
        gl_FragColor=vec4(lit+lights+vec3(0.25,0.5,1.0)*rim*0.6*(0.2+day),1.0);
      }`,
  });
  const globe = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), mat);
  globe.rotation.z = 0.41; // 地軸の傾き
  const spin = new THREE.Group(); spin.add(globe); scene.add(spin);

  const cloudMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, uniforms: { sunDir: { value: sun } },
    vertexShader: `varying vec3 vP; varying vec3 vN; void main(){ vP=position; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader: NOISE + `uniform vec3 sunDir; varying vec3 vP; varying vec3 vN;
      void main(){ float c=smoothstep(0.15,0.55,fbm(vP*2.4+vec3(8.0))); float d=max(dot(normalize(vN),sunDir),0.0);
        gl_FragColor=vec4(vec3(1.0)*(0.08+0.95*d),c*0.75); }`,
  });
  const clouds = new THREE.Mesh(new THREE.SphereGeometry(1.012, 96, 64), cloudMat);
  clouds.rotation.z = 0.41; scene.add(clouds);

  const atm = new THREE.Mesh(new THREE.SphereGeometry(1.09, 64, 48), new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: { sunDir: { value: sun } },
    vertexShader: `varying vec3 vN; varying vec3 vW; void main(){ vN=normalize(mat3(modelMatrix)*normal); vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform vec3 sunDir; varying vec3 vN; varying vec3 vW;
      void main(){ vec3 V=normalize(cameraPosition-vW); float r=pow(0.72-dot(normalize(vN),V),3.0);
        float d=0.25+0.75*smoothstep(-0.3,0.6,dot(normalize(vN),sunDir)); gl_FragColor=vec4(vec3(0.3,0.6,1.0)*r*2.2*d,1.0); }`,
  }));
  scene.add(atm);

  const hours = p.hours ?? 24, start = p.start_hour ?? 6;
  return {
    scene, camera,
    update(t, dur) {
      const h = start + hours * (t / dur);
      spin.rotation.y = (h / 24) * Math.PI * 2;
      clouds.rotation.y = spin.rotation.y * 1.08 + 0.3;
      const a = -0.5 + 0.25 * (t / dur);
      const dist = (p.dist ?? 5.6) - 0.4 * (t / dur);
      camera.position.set(Math.sin(a) * dist, 0.35, Math.cos(a) * dist);
      camera.lookAt(0, 0.28, 0);
    },
  };
}

// ------------------------------------------------------------------ 部屋（タイムラプス）
function skyColor(h) {
  // h: 0〜24時。昼は青、夕方はオレンジ、夜は紺
  const stops = [[0, 0x0b1026], [5, 0x1b2550], [6.5, 0xf2a65a], [8, 0x8ec5ff], [16, 0x8ec5ff], [18, 0xf08a4b], [19.5, 0x1b2550], [24, 0x0b1026]];
  for (let i = 0; i < stops.length - 1; i++) {
    const [h0, c0] = stops[i], [h1, c1] = stops[i + 1];
    if (h >= h0 && h <= h1) return new THREE.Color(c0).lerp(new THREE.Color(c1), (h - h0) / (h1 - h0));
  }
  return new THREE.Color(0x0b1026);
}

function room(p) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d0f1a);
  const camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.1, 100);
  const std = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, ...o });
  const box = (w, h, d, m, x, y, z) => { const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); b.position.set(x, y, z); b.castShadow = b.receiveShadow = true; scene.add(b); return b; };

  // 床・壁
  box(10, 0.1, 8, std(0xc9a27a), 0, -0.05, 0);
  const wallM = std(0xe8e1d6);
  box(10, 5, 0.1, wallM, 0, 2.5, -3);
  box(0.1, 5, 8, std(0xdcd4c7), -4, 2.5, 0);
  // 窓（外の空）
  const skyM = new THREE.MeshBasicMaterial({ color: 0x8ec5ff });
  const sky = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 1.6), skyM); sky.position.set(1.6, 2.7, -2.94); scene.add(sky);
  const frameM = std(0xffffff);
  box(2.4, 0.1, 0.12, frameM, 1.6, 3.55, -2.9); box(2.4, 0.1, 0.12, frameM, 1.6, 1.85, -2.9);
  box(0.1, 1.8, 0.12, frameM, 0.45, 2.7, -2.9); box(0.1, 1.8, 0.12, frameM, 2.75, 2.7, -2.9); box(0.06, 1.7, 0.1, frameM, 1.6, 2.7, -2.9);
  // 太陽・月
  const orb = new THREE.Mesh(new THREE.CircleGeometry(0.16, 32), new THREE.MeshBasicMaterial({ color: 0xfff3c4 }));
  scene.add(orb);
  // 机・ノートパソコン
  const wood = std(0x8a5a3b);
  box(2.4, 0.08, 1.1, wood, -0.6, 1.15, -1.9);
  for (const [x, z] of [[-1.7, -2.35], [0.5, -2.35], [-1.7, -1.45], [0.5, -1.45]]) box(0.08, 1.15, 0.08, wood, x, 0.575, z);
  box(0.9, 0.04, 0.6, std(0x3a3f4b), -0.6, 1.21, -1.85);
  const screenM = new THREE.MeshStandardMaterial({ color: 0x1b2230, emissive: 0x7fb4ff, emissiveIntensity: 1.0 });
  const scr = box(0.9, 0.58, 0.03, screenM, -0.6, 1.52, -2.15); scr.rotation.x = -0.18;
  const screenLight = new THREE.PointLight(0x9cc4ff, 1.5, 4, 2); screenLight.position.set(-0.6, 1.55, -1.7); scene.add(screenLight);
  // ベッド（使われないまま）
  box(2.2, 0.45, 3.0, std(0x6b4a36), -2.75, 0.25, 0.9);
  box(2.1, 0.22, 2.9, std(0xf5f5f5), -2.75, 0.58, 0.9);
  box(2.1, 0.12, 1.9, std(0x5b7bd5), -2.75, 0.73, 1.35);
  box(0.9, 0.18, 0.5, std(0xffffff), -2.75, 0.78, -0.3);
  // 時計
  const clockFace = new THREE.Mesh(new THREE.CircleGeometry(0.38, 48), std(0xffffff)); clockFace.position.set(-2.9, 3.3, -2.94); scene.add(clockFace);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.39, 0.035, 12, 48), std(0x333344)); ring.position.copy(clockFace.position); scene.add(ring);
  const hand = (len, w, c) => { const g = new THREE.Group(); const m = new THREE.Mesh(new THREE.BoxGeometry(w, len, 0.02), new THREE.MeshBasicMaterial({ color: c })); m.position.y = len / 2; g.add(m); g.position.set(-2.9, 3.3, -2.92); scene.add(g); return g; };
  const hourH = hand(0.2, 0.05, 0x222233), minH = hand(0.31, 0.03, 0x222233);
  // 椅子と人
  box(0.7, 0.08, 0.7, std(0x444a5a), -0.6, 0.75, -1.0); box(0.7, 0.8, 0.08, std(0x444a5a), -0.6, 1.15, -0.65);
  const person = new THREE.Group(); person.position.set(-0.6, 0.79, -1.05); scene.add(person);
  const skin = std(0xffd6aa), shirt = std(0x58a6ff), hair = std(0x2d2337);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.26, 0.45, 8, 16), shirt); body.position.y = 0.5; body.castShadow = true; person.add(body);
  const neck = new THREE.Group(); neck.position.y = 0.92; person.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.24, 32, 24), skin); head.position.y = 0.2; head.castShadow = true; neck.add(head);
  const hairM = new THREE.Mesh(new THREE.SphereGeometry(0.25, 32, 24, 0, Math.PI * 2, 0, Math.PI * 0.5), hair); hairM.position.y = 0.22; hairM.rotation.x = 0.25; neck.add(hairM);
  for (const s of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.08, 0.45, 6, 10), shirt);
    arm.position.set(s * 0.3, 0.55, -0.22); arm.rotation.x = 1.2; person.add(arm);
  }
  // 光
  const hemi = new THREE.HemisphereLight(0xbfd4ff, 0x3a2a20, 0.35); scene.add(hemi);
  const sunL = new THREE.DirectionalLight(0xffffff, 2.0); sunL.castShadow = true; sunL.shadow.mapSize.set(1024, 1024);
  sunL.shadow.camera.left = -6; sunL.shadow.camera.right = 6; sunL.shadow.camera.top = 6; sunL.shadow.camera.bottom = -6;
  scene.add(sunL); scene.add(sunL.target); sunL.target.position.set(0, 0, 0);
  const lamp = new THREE.PointLight(0xffc27a, 0, 9, 1.6); lamp.position.set(0.5, 3.6, -0.5); lamp.castShadow = true; scene.add(lamp);

  const start = p.start_hour ?? 7, hours = p.hours ?? 24;
  return {
    scene, camera,
    update(t, dur) {
      const H = start + hours * (t / dur), h = ((H % 24) + 24) % 24;
      skyM.color = skyColor(h);
      const ang = ((h - 6) / 12) * Math.PI; // 6時に昇り18時に沈む
      const up = Math.sin(ang);
      orb.position.set(1.6 + 0.9 * Math.cos(ang) * (h >= 6 && h <= 18 ? 1 : -1), 2.15 + 1.1 * Math.abs(up), -2.96);
      orb.material.color.set(h >= 6 && h <= 18 ? 0xfff3c4 : 0xdfe6ff);
      const dayK = Math.max(0, up);
      sunL.intensity = 2.6 * dayK; sunL.color = skyColor(h).lerp(new THREE.Color(0xffffff), 0.6);
      sunL.position.set(3 + 2 * Math.cos(ang), 2 + 4 * dayK, 3);
      lamp.intensity = 6 * (1 - Math.min(1, dayK * 3));
      hemi.intensity = 0.15 + 0.35 * dayK;
      scene.background = skyColor(h).multiplyScalar(0.18);
      hourH.rotation.z = -(H % 12) / 12 * Math.PI * 2; minH.rotation.z = -(H % 1) * Math.PI * 2;
      // 居眠り：ときどき頭がカクッと落ちて、はっと戻る
      let nod = 0;
      if (p.nod) { const ph = (t * 0.55) % 1; nod = ph < 0.55 ? 0.05 * Math.sin(t * 2) : ph < 0.8 ? 0.55 * Math.sin(((ph - 0.55) / 0.25) * Math.PI * 0.5) : 0.55 * (1 - (ph - 0.8) / 0.2) ** 3; }
      neck.rotation.x = 0.12 + nod; neck.rotation.z = 0.04 * Math.sin(t * 0.8);
      person.rotation.y = 0.02 * Math.sin(t * 0.5);
      screenM.emissiveIntensity = 0.9 + 0.1 * Math.sin(t * 7);
      const a = 0.55 + 0.25 * (t / dur);
      camera.position.set(Math.sin(a) * 6.2, 3.1, Math.cos(a) * 6.2 + 0.5);
      camera.lookAt(-0.6, 1.5, -1.2);
    },
  };
}

// ------------------------------------------------------------------ 脳
function brain(p) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a1a);
  const camera = new THREE.PerspectiveCamera(34, 16 / 9, 0.1, 100);
  scene.add(starfield(800, 40));
  const mat = new THREE.ShaderMaterial({
    uniforms: { dirt: { value: 0 } },
    vertexShader: NOISE + `varying float vD; varying vec3 vN; varying vec3 vW; varying vec3 vP;
      float gy(vec3 p){ float nz=snoise(p*vec3(4.2,5.2,3.6))+0.35*snoise(p*9.0); return smoothstep(0.0,0.42,abs(nz)); }
      vec3 disp(vec3 p){ vec3 n=normalize(p); float mid=exp(-p.x*p.x*110.0);
        float d=0.07*gy(p)-0.035-0.2*mid; return (n+n*d)*vec3(0.92,0.8,1.12); }
      void main(){ vec3 p=normalize(position); vec3 q=disp(p);
        vec3 t1=normalize(cross(p,abs(p.y)<0.95?vec3(0.0,1.0,0.0):vec3(1.0,0.0,0.0))); vec3 t2=cross(p,t1);
        float e=0.006; vec3 qa=disp(normalize(p+t1*e)); vec3 qb=disp(normalize(p+t2*e));
        vec3 nn=normalize(cross(qa-q,qb-q)); if(dot(nn,q)<0.0) nn=-nn;
        float mid=exp(-p.x*p.x*110.0); vD=gy(p)-mid*1.5; vP=p;
        vN=normalize(mat3(modelMatrix)*nn); vec4 w=modelMatrix*vec4(q,1.0); vW=w.xyz;
        gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: NOISE + `uniform float dirt; varying float vD; varying vec3 vN; varying vec3 vW; varying vec3 vP;
      void main(){ vec3 n=normalize(vN); vec3 L=normalize(vec3(0.6,0.8,0.7)); vec3 V=normalize(cameraPosition-vW);
        vec3 base=mix(vec3(0.55,0.22,0.30),vec3(0.98,0.64,0.68),smoothstep(0.0,0.7,vD));
        float spot=smoothstep(0.35,0.75,snoise(vP*9.0)*0.5+0.5)*dirt;
        base=mix(base,vec3(0.42,0.36,0.22),spot);
        float l=0.35+0.75*max(dot(n,L),0.0); float rim=pow(1.0-max(dot(n,V),0.0),2.5);
        gl_FragColor=vec4(base*l+vec3(1.0,0.7,0.75)*rim*0.35,1.0); }`,
  });
  const b = new THREE.Mesh(new THREE.SphereGeometry(1, 256, 192), mat); scene.add(b);

  // 粒（老廃物）
  const N = 900, r_ = rand(11);
  const seeds = Array.from({ length: N }, () => { const u = r_() * 2 - 1, th = r_() * Math.PI * 2, s = Math.sqrt(1 - u * u); return [s * Math.cos(th), u, s * Math.sin(th), r_(), r_()]; });
  const pos = new Float32Array(N * 3), g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const dirty = p.mode === 'dirty';
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: dirty ? 0xb59a5a : 0x7fd0ff, size: dirty ? 0.045 : 0.06, transparent: true, opacity: 0.95, depthWrite: false, blending: dirty ? THREE.NormalBlending : THREE.AdditiveBlending }));
  scene.add(pts);
  return {
    scene, camera,
    update(t, dur) {
      const k = t / dur;
      for (let i = 0; i < N; i++) {
        const [x, y, z, ph, sp] = seeds[i];
        let r;
        if (dirty) { r = (ph < k * 1.2) ? 1.08 + 0.05 * sp : 0; }            // 時間とともに表面にたまっていく
        else { r = 0.6 + (((t * (0.25 + 0.35 * sp)) + ph) % 1) * 1.8; }    // 中から外へ流れ出ていく
        pos.set([x * r * 0.92, y * r * 0.8, z * r * 1.12], i * 3);
      }
      g.attributes.position.needsUpdate = true;
      mat.uniforms.dirt.value = dirty ? Math.min(1, k * 1.3) : 0;
      b.rotation.y = 0.4 + t * 0.25; pts.rotation.y = b.rotation.y;
      camera.position.set(0, 1.0, 6.0 - 0.5 * k); camera.lookAt(0, 0.12, 0);
    },
  };
}

export const SCENES = { earth, room, brain };
export { THREE };
