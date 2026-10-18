import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** unsupported: navegador sem Push · insecure: página sem HTTPS · denied: permissão negada · off/on: desativado/ativo neste navegador */
export type PushState = 'unsupported' | 'insecure' | 'denied' | 'off' | 'on';

/** Converte a chave pública VAPID (base64url) no formato que `pushManager.subscribe` exige. */
export function urlBase64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

@Injectable({ providedIn: 'root' })
export class PushService {
  private http = inject(HttpClient);
  private base = '/api/v1/notifications/push';

  state = signal<PushState>('off');
  devices = signal(0);

  /** Quando o navegador permite Push: contexto seguro (HTTPS ou localhost) com Service Worker e PushManager. */
  support(): PushState | 'ok' {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      return window?.isSecureContext === false ? 'insecure' : 'unsupported';
    }
    return window.isSecureContext ? 'ok' : 'insecure';
  }

  private async registration(): Promise<ServiceWorkerRegistration> {
    return navigator.serviceWorker.register('/push-sw.js', { scope: '/' });
  }

  async refresh(): Promise<void> {
    const support = this.support();
    if (support !== 'ok') {
      this.state.set(support);
      return;
    }
    try {
      const status = await firstValueFrom(this.http.get<{ devices: number }>(`${this.base}/status`));
      this.devices.set(status.devices);
    } catch {
      /* só informativo */
    }
    if (Notification.permission === 'denied') {
      this.state.set('denied');
      return;
    }
    const reg = await navigator.serviceWorker.getRegistration('/');
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    this.state.set(sub ? 'on' : 'off');
  }

  /** Pede permissão, inscreve este navegador e registra no servidor. Lança Error com mensagem em português. */
  async enable(): Promise<void> {
    if (this.support() !== 'ok') throw new Error('Este navegador ou endereço não permite notificações (é preciso HTTPS ou localhost).');
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      this.state.set(permission === 'denied' ? 'denied' : 'off');
      throw new Error('A permissão de notificações não foi concedida.');
    }
    const { public_key } = await firstValueFrom(this.http.get<{ public_key: string }>(`${this.base}/public-key`));
    const reg = await this.registration();
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToBytes(public_key) });
    }
    const json = sub.toJSON();
    const res = await firstValueFrom(
      this.http.post<{ devices: number }>(`${this.base}/subscribe`, { endpoint: json.endpoint, keys: json.keys })
    );
    this.devices.set(res.devices);
    this.state.set('on');
  }

  async disable(): Promise<void> {
    const reg = await navigator.serviceWorker.getRegistration('/');
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) {
      const res = await firstValueFrom(this.http.post<{ devices: number }>(`${this.base}/unsubscribe`, { endpoint: sub.endpoint }));
      this.devices.set(res.devices);
      await sub.unsubscribe();
    }
    this.state.set('off');
  }

  test(): Promise<unknown> {
    return firstValueFrom(this.http.post(`${this.base}/test`, {}));
  }
}
