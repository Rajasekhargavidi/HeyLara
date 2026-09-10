import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js';
import { createTicker, lerp } from './animations.js';

export class JarvisCore {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
    this.camera.position.z = 8;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.container.appendChild(this.renderer.domElement);
    this.root = new THREE.Group();
    this.scene.add(this.root);
    this.state = 'idle';
    this.intensity = .45;
    this.build();
    this.resize();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.stop = createTicker((delta, seconds) => this.render(delta, seconds));
  }

  build() {
    const cyan = new THREE.MeshBasicMaterial({ color: 0x65e9ff, transparent: true, opacity: .92, blending: THREE.AdditiveBlending });
    const violet = new THREE.MeshBasicMaterial({ color: 0x936dff, transparent: true, opacity: .48, blending: THREE.AdditiveBlending });
    this.shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.25, 2), new THREE.MeshBasicMaterial({ color: 0x1f7fa8, wireframe: true, transparent: true, opacity: .55, blending: THREE.AdditiveBlending }));
    this.inner = new THREE.Mesh(new THREE.IcosahedronGeometry(.8, 2), cyan);
    this.inner.scale.setScalar(.75);
    this.ringA = new THREE.Mesh(new THREE.TorusGeometry(1.55, .025, 8, 96), cyan);
    this.ringB = new THREE.Mesh(new THREE.TorusGeometry(1.8, .012, 8, 96), violet);
    this.ringC = new THREE.Mesh(new THREE.TorusGeometry(2.05, .008, 8, 96), cyan);
    this.ringA.rotation.x = Math.PI / 2.3;
    this.ringB.rotation.y = Math.PI / 3;
    this.ringC.rotation.x = Math.PI / 2;
    this.root.add(this.shell, this.inner, this.ringA, this.ringB, this.ringC);
    const particles = new THREE.BufferGeometry();
    const positions = new Float32Array(260 * 3);
    for (let i = 0; i < 260; i += 1) {
      const radius = 2.1 + Math.random() * .55;
      const angle = Math.random() * Math.PI * 2;
      positions.set([Math.cos(angle) * radius, (Math.random() - .5) * 2.2, Math.sin(angle) * radius], i * 3);
    }
    particles.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.sparks = new THREE.Points(particles, new THREE.PointsMaterial({ color: 0x65e9ff, size: .035, transparent: true, opacity: .8, blending: THREE.AdditiveBlending }));
    this.root.add(this.sparks);
  }

  setState(state) {
    this.state = state;
    this.intensity = { idle: .45, listening: .9, thinking: .7, speaking: 1 }[state] || .45;
  }

  render(delta, seconds) {
    const target = { idle: .45, listening: .9, thinking: .7, speaking: 1 }[this.state] || .45;
    this.intensity = lerp(this.intensity, target, delta * 5);
    this.root.rotation.y += delta * (.12 + this.intensity * .15);
    this.root.rotation.x = Math.sin(seconds * .7) * .08;
    this.shell.rotation.z -= delta * .25;
    this.ringA.rotation.z += delta * .75;
    this.ringB.rotation.x -= delta * .38;
    this.ringC.rotation.z -= delta * .2;
    const scale = 1 + Math.sin(seconds * (2 + this.intensity * 4)) * .035 * this.intensity;
    this.inner.scale.setScalar(.75 * scale);
    this.inner.material.opacity = .65 + this.intensity * .3;
    this.sparks.rotation.y -= delta * .25;
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    const width = Math.max(this.container.clientWidth, 1);
    const height = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  destroy() { this.stop(); this.resizeObserver.disconnect(); this.renderer.dispose(); }
}
