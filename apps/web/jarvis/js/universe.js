import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js';
import { createTicker } from './animations.js';

export class Universe {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 1400);
    this.camera.position.z = 260;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(innerWidth, innerHeight);
    container.appendChild(this.renderer.domElement);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.makeStars();
    this.makeGrid();
    this.resize = this.resize.bind(this);
    addEventListener('resize', this.resize);
    this.stop = createTicker((delta, seconds) => this.render(delta, seconds));
  }

  makeStars() {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(1700 * 3);
    const colors = new Float32Array(1700 * 3);
    for (let i = 0; i < 1700; i += 1) {
      const radius = 220 + Math.random() * 540;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos((Math.random() * 2) - 1);
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi) - 180;
      const color = new THREE.Color().setHSL(0.52 + Math.random() * 0.13, .7, .55 + Math.random() * .35);
      colors.set([color.r, color.g, color.b], i * 3);
    }
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({ size: 1.25, transparent: true, opacity: .7, vertexColors: true, blending: THREE.AdditiveBlending });
    this.stars = new THREE.Points(geometry, material);
    this.group.add(this.stars);
  }

  makeGrid() {
    const grid = new THREE.GridHelper(850, 34, 0x1c5b82, 0x0a2940);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -300;
    grid.material.transparent = true;
    grid.material.opacity = .18;
    this.group.add(grid);
  }

  render(delta, seconds) {
    this.stars.rotation.y += delta * .008;
    this.stars.rotation.x = Math.sin(seconds * .05) * .04;
    this.group.position.y = Math.sin(seconds * .15) * 3;
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    this.camera.aspect = innerWidth / innerHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(innerWidth, innerHeight);
  }

  destroy() { this.stop(); removeEventListener('resize', this.resize); this.renderer.dispose(); }
}
