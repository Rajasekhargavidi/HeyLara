import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js';
import { createTicker } from './animations.js';

const AGENTS = [
  ['social_media_agent', 'Social Media', 0x65e9ff], ['knowledge_agent', 'Knowledge / RAG', 0xb38aff],
  ['technology_intelligence_agent', 'Technology Intel', 0xffc76c], ['customer_engagement_agent', 'Customer Engagement', 0x5ff3b3],
  ['crm_agent', 'Lead / CRM', 0x65e9ff], ['analytics_agent', 'Analytics', 0xff7189], ['employee_agent', 'Employee Tasks', 0xb38aff],
];

export class AgentConstellation {
  constructor(container, onSelect) {
    this.container = container; this.onSelect = onSelect; this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, .1, 100); this.camera.position.z = 9;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); container.appendChild(this.renderer.domElement);
    this.group = new THREE.Group(); this.scene.add(this.group); this.nodes = []; this.drag = null; this.pointer = new THREE.Vector2();
    this.build(); this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(container); this.resize();
    this.renderer.domElement.addEventListener('pointerdown', (event) => { this.drag = { x: event.clientX, y: event.clientY }; });
    this.renderer.domElement.addEventListener('pointermove', (event) => { if (this.drag) { this.group.rotation.y += (event.clientX - this.drag.x) * .006; this.group.rotation.x += (event.clientY - this.drag.y) * .004; this.drag = { x: event.clientX, y: event.clientY }; } });
    this.renderer.domElement.addEventListener('pointerup', () => { this.drag = null; });
    this.renderer.domElement.addEventListener('click', (event) => this.selectAt(event));
    this.stop = createTicker((delta, seconds) => this.render(delta, seconds));
  }

  build() {
    const positions = [[0, 0, 0], [-2.7, 1.15, -.2], [2.7, 1, -.4], [-2.4, -1.3, .2], [2.5, -1.2, .1], [-.7, 2.05, -.2], [.8, -2, -.3]];
    const points = [];
    AGENTS.forEach(([id, label, color], index) => {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(index === 0 ? .38 : .23, 16, 16), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .95 }));
      mesh.position.set(...positions[index]); mesh.userData = { id, label, color, baseY: mesh.position.y }; this.group.add(mesh); this.nodes.push(mesh); points.push(mesh.position);
      const glow = new THREE.Mesh(new THREE.SphereGeometry(index === 0 ? .58 : .38, 12, 12), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .08, blending: THREE.AdditiveBlending }));
      mesh.add(glow);
    });
    const linePositions = [];
    for (let i = 1; i < points.length; i += 1) linePositions.push(...points[0].toArray(), ...points[i].toArray());
    const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
    this.lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: 0x458bff, transparent: true, opacity: .3 }));
    this.group.add(this.lines);
  }

  selectAt(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1; this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const raycaster = new THREE.Raycaster(); raycaster.setFromCamera(this.pointer, this.camera);
    const hit = raycaster.intersectObjects(this.nodes)[0]; if (hit && this.onSelect) this.onSelect(hit.object.userData);
  }

  render(delta, seconds) {
    this.group.rotation.y += delta * .05;
    this.nodes.forEach((node, index) => { node.scale.setScalar(1 + Math.sin(seconds * 2 + index) * .1); node.position.y = node.userData.baseY + Math.sin(seconds * .7 + index) * .03; });
    this.renderer.render(this.scene, this.camera);
  }
  resize() { const w = Math.max(this.container.clientWidth, 1), h = Math.max(this.container.clientHeight, 1); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.renderer.setSize(w, h, false); }
  destroy() { this.stop(); this.resizeObserver.disconnect(); this.renderer.dispose(); }
}

export { AGENTS };
