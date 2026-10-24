import { Component, computed, inject } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { RouterLink } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { AuthService } from '../../core/auth/auth.service';
import { ChannelsComponent } from '../notifications/admin/channels.component';
import { SlackConfigComponent } from '../notifications/admin/slack-config.component';
import { TelegramConfigComponent } from '../notifications/admin/telegram-config.component';
import { WhatsAppConfigComponent } from '../notifications/admin/whatsapp-config.component';
import { EmailConfigComponent } from './email-config.component';

/** Permissões que o backend exige hoje (sem criar nenhuma nova): o e-mail aceita qualquer uma das duas. */
export const EMAIL_PERMISSIONS = ['notifications.manage', 'system.backup.manage'];
export const MANAGE_PERMISSION = 'notifications.manage';

/**
 * Página única dos canais de comunicação, uma aba por gateway (ADR-019).
 * Cada aba só aparece para quem pode usá-la e traz o estado do canal, a configuração e o caminho para as regras.
 */
@Component({
  selector: 'app-channels-page',
  standalone: true,
  imports: [
    NgTemplateOutlet, RouterLink, MatTabsModule, MatIconModule,
    ChannelsComponent, EmailConfigComponent, WhatsAppConfigComponent, TelegramConfigComponent, SlackConfigComponent
  ],
  template: `
    <div class="page">
      <h1>Canais de comunicação</h1>
      <p class="subtitle">Configure, teste e acompanhe cada canal que o sistema usa para avisar as pessoas.</p>

      <mat-tab-group animationDuration="0ms" mat-stretch-tabs="false" data-testid="channel-tabs">
        @if (canEmail()) {
          <mat-tab label="E-mail">
            <ng-template matTabContent>
              <div class="tab">
                @if (canManage()) { <app-channels only="email" /> }
                <app-email-config />
                <ng-container *ngTemplateOutlet="rulesLink" />
              </div>
            </ng-template>
          </mat-tab>
        }
        @if (canManage()) {
          <mat-tab label="WhatsApp">
            <ng-template matTabContent>
              <div class="tab">
                <app-channels only="whatsapp" />
                <app-whatsapp-config />
                <ng-container *ngTemplateOutlet="rulesLink" />
              </div>
            </ng-template>
          </mat-tab>
          <mat-tab label="Telegram">
            <ng-template matTabContent>
              <div class="tab">
                <app-channels only="telegram" />
                <app-telegram-config />
                <ng-container *ngTemplateOutlet="rulesLink" />
              </div>
            </ng-template>
          </mat-tab>
          <mat-tab label="Slack">
            <ng-template matTabContent>
              <div class="tab">
                <app-channels only="slack" />
                <app-slack-config />
                <ng-container *ngTemplateOutlet="rulesLink" />
              </div>
            </ng-template>
          </mat-tab>
        }
      </mat-tab-group>

      <ng-template #rulesLink>
        @if (canManage()) {
          <p class="rules-link">
            <mat-icon>rule</mat-icon>
            Quais avisos usam este canal? Veja e ajuste em <a routerLink="/notifications/admin" data-testid="rules-link">Entregas e regras</a>.
          </p>
        }
      </ng-template>
    </div>
  `,
  styles: [`
    .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
    h1 { margin: 0; font-size: 24px; }
    .subtitle { margin: 4px 0 16px; color: #64748b; }
    .tab { padding-top: 8px; }
    .rules-link { display: flex; align-items: center; gap: 8px; margin: 20px 0 0; font-size: 13px; color: #475569; }
  `]
})
export class ChannelsPageComponent {
  private auth = inject(AuthService);

  canManage = computed(() => this.auth.hasPermission(MANAGE_PERMISSION));
  canEmail = computed(() => EMAIL_PERMISSIONS.some((p) => this.auth.hasPermission(p)));
}
