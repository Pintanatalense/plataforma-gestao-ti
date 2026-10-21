import { Component, Inject, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { Asset, AssetService } from '../../../core/services/asset.service';

export interface AssetQuickViewData {
  asset: Asset;
}

@Component({
  selector: 'app-asset-quick-view-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule
  ],
  template: `
    <div class="quick-view-container">
      <div class="dialog-header">
        <div class="title-area">
          <div class="title-row">
            <h2>{{ asset.name }}</h2>
            <span class="tag-badge">#{{ asset.tag }}</span>
            <span class="tag-badge" *ngIf="asset.serial_number">SN: {{ asset.serial_number }}</span>
          </div>
          <span class="category-name">{{ asset.category?.name || 'Sem categoria' }}</span>
        </div>

        <div class="header-actions">
          <span class="status-badge" [ngClass]="getStatusBadgeClass(asset.status)">
            {{ getStatusLabel(asset.status) }}
          </span>
          <button mat-icon-button mat-dialog-close class="close-btn" matTooltip="Fechar">
            <mat-icon>close</mat-icon>
          </button>
        </div>
      </div>

      <mat-dialog-content class="dialog-body">
        <!-- INFO GRID -->
        <div class="info-summary-grid">
          <div class="info-cell">
            <span class="cell-label">Unidade / Lotação</span>
            <span class="cell-value">
              <mat-icon class="cell-icon">domain</mat-icon>
              {{ displayedUnit }}
            </span>
          </div>

          <div class="info-cell">
            <span class="cell-label">Responsável / Custodiante</span>
            <span class="cell-value" [class.in-stock]="!asset.employee_id">
              <mat-icon class="cell-icon">{{ asset.employee_id ? 'person' : 'inventory_2' }}</mat-icon>
              {{ displayedEmployee }}
            </span>
          </div>

          <div class="info-cell">
            <span class="cell-label">Aquisição</span>
            <span class="cell-value">
              <mat-icon class="cell-icon">shopping_bag</mat-icon>
              {{ asset.purchase_date ? (asset.purchase_date | date:'dd/MM/yyyy') : 'Não informada' }}
            </span>
          </div>

          <div class="info-cell">
            <span class="cell-label">Situação da Garantia</span>
            <span class="cell-value">
              <span *ngIf="asset.warranty_expires; else noWarranty">
                <span class="warranty-tag" [class.active]="isWarrantyActive" [class.expired]="!isWarrantyActive">
                  <mat-icon>{{ isWarrantyActive ? 'verified' : 'history_toggle_off' }}</mat-icon>
                  {{ isWarrantyActive ? 'Vigente até ' + (asset.warranty_expires | date:'dd/MM/yyyy') : 'Expirada em ' + (asset.warranty_expires | date:'dd/MM/yyyy') }}
                </span>
              </span>
              <ng-template #noWarranty>
                <span class="muted-text">Sem garantia cadastrada</span>
              </ng-template>
            </span>
          </div>
        </div>

        <!-- SPECS SECTION -->
        <div class="specs-section">
          <div class="section-title">
            <mat-icon>memory</mat-icon>
            <h3>Especificações Técnicas do Equipamento</h3>
          </div>

          <div class="specs-grid" *ngIf="specEntries.length > 0; else noSpecs">
            <div class="spec-card" *ngFor="let spec of specEntries">
              <div class="icon-wrap">
                <mat-icon>{{ getSpecIcon(spec[0]) }}</mat-icon>
              </div>
              <div class="spec-text">
                <span class="spec-label">{{ getSpecLabel(spec[0]) }}</span>
                <span class="spec-value">{{ spec[1] }}</span>
              </div>
            </div>
          </div>

          <ng-template #noSpecs>
            <div class="empty-state">
              <mat-icon>devices_other</mat-icon>
              <p>Nenhuma especificação técnica detalhada registrada para este item.</p>
            </div>
          </ng-template>
        </div>

        <!-- NOTES SECTION -->
        <div class="notes-section" *ngIf="asset.notes">
          <span class="cell-label">Observações / Dados Fiscais</span>
          <div class="notes-content">
            <mat-icon>article</mat-icon>
            <p>{{ asset.notes }}</p>
          </div>
        </div>
      </mat-dialog-content>

      <mat-dialog-actions class="dialog-actions">
        <button *ngIf="asset.employee_id" mat-stroked-button class="print-btn" (click)="printStatement()">
          <mat-icon>print</mat-icon> Termo de Cautela
        </button>
        <span class="spacer"></span>
        <button mat-button mat-dialog-close>Fechar</button>
        <button mat-flat-button color="primary" (click)="goToFullDetail()">
          <mat-icon>open_in_new</mat-icon> Ver Página Completa
        </button>
      </mat-dialog-actions>
    </div>
  `,
  styles: [`
    .quick-view-container {
      display: flex;
      flex-direction: column;
      max-width: 680px;
      min-width: 520px;
      padding: 6px;

      @media (max-width: 600px) {
        min-width: 90vw;
      }
    }

    .dialog-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 16px 20px 12px;
      border-bottom: 1px solid #e2e8f0;
      gap: 16px;

      .title-area {
        display: flex;
        flex-direction: column;
        gap: 4px;

        .title-row {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;

          h2 {
            margin: 0;
            font-size: 19px;
            font-weight: 700;
            color: #0f172a;
          }

          .tag-badge {
            font-family: ui-monospace, SFMono-Regular, monospace;
            background: #f1f5f9;
            color: #334155;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            border: 1px solid #e2e8f0;
          }
        }

        .category-name {
          font-size: 13px;
          color: #64748b;
        }
      }

      .header-actions {
        display: flex;
        align-items: center;
        gap: 10px;

        .close-btn {
          color: #64748b;
        }

        .status-badge {
          padding: 4px 10px;
          border-radius: 14px;
          font-size: 12px;
          font-weight: 600;

          &.status-in_stock { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
          &.status-in_use { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
          &.status-maintenance { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
          &.status-decommissioned { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
          &.status-default { background: #f1f5f9; color: #475569; }
        }
      }
    }

    .dialog-body {
      padding: 20px !important;
      display: flex;
      flex-direction: column;
      gap: 20px;
      max-height: 70vh;
      overflow-y: auto;
    }

    .info-summary-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;

      @media (max-width: 500px) {
        grid-template-columns: 1fr;
      }

      .info-cell {
        display: flex;
        flex-direction: column;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 12px;

        .cell-label {
          font-size: 11px;
          color: #64748b;
          text-transform: uppercase;
          font-weight: 600;
          letter-spacing: 0.04em;
          margin-bottom: 4px;
        }

        .cell-value {
          font-size: 13px;
          font-weight: 600;
          color: #1e293b;
          display: flex;
          align-items: center;
          gap: 6px;

          .cell-icon {
            font-size: 16px;
            width: 16px;
            height: 16px;
            color: #2563eb;
          }

          &.in-stock {
            color: #059669;
            .cell-icon { color: #059669; }
          }
        }

        .warranty-tag {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11.5px;
          font-weight: 600;

          mat-icon {
            font-size: 14px;
            width: 14px;
            height: 14px;
          }

          &.active {
            background: #ecfdf5;
            color: #059669;
          }

          &.expired {
            background: #fef2f2;
            color: #dc2626;
          }
        }

        .muted-text {
          color: #94a3b8;
          font-size: 12px;
          font-weight: 400;
        }
      }
    }

    .specs-section {
      display: flex;
      flex-direction: column;
      gap: 10px;

      .section-title {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #0f172a;

        mat-icon {
          color: #7c3aed;
          font-size: 20px;
          width: 20px;
          height: 20px;
        }

        h3 {
          margin: 0;
          font-size: 14px;
          font-weight: 700;
        }
      }

      .specs-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;

        @media (max-width: 500px) {
          grid-template-columns: 1fr;
        }

        .spec-card {
          display: flex;
          align-items: center;
          gap: 10px;
          background: #ffffff;
          border: 1px solid #e2e8f0;
          border-radius: 8px;
          padding: 8px 12px;

          .icon-wrap {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            border-radius: 6px;
            background: #ede9fe;
            color: #7c3aed;
            flex-shrink: 0;

            mat-icon {
              font-size: 17px;
              width: 17px;
              height: 17px;
            }
          }

          .spec-text {
            display: flex;
            flex-direction: column;

            .spec-label {
              font-size: 10.5px;
              color: #64748b;
              font-weight: 600;
              text-transform: uppercase;
            }

            .spec-value {
              font-size: 13px;
              font-weight: 600;
              color: #0f172a;
            }
          }
        }
      }

      .empty-state {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 14px;
        background: #f8fafc;
        border: 1px dashed #cbd5e1;
        border-radius: 8px;
        color: #64748b;
        font-size: 13px;

        mat-icon {
          color: #94a3b8;
        }

        p { margin: 0; }
      }
    }

    .notes-section {
      display: flex;
      flex-direction: column;
      gap: 6px;

      .cell-label {
        font-size: 11px;
        color: #64748b;
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.04em;
      }

      .notes-content {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 12px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          color: #64748b;
          margin-top: 2px;
        }

        p {
          margin: 0;
          font-size: 12.5px;
          color: #334155;
          line-height: 1.4;
        }
      }
    }

    .dialog-actions {
      padding: 12px 20px !important;
      border-top: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;

      .spacer {
        flex: 1;
      }

      .print-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
      }
    }
  `]
})
export class AssetQuickViewDialogComponent {
  private router = inject(Router);
  private assetService = inject(AssetService);
  private dialogRef = inject(MatDialogRef<AssetQuickViewDialogComponent>);

  asset: Asset;
  specEntries: [string, any][] = [];

  constructor(@Inject(MAT_DIALOG_DATA) public data: AssetQuickViewData) {
    this.asset = data.asset;
    this.specEntries = this.asset.technical_specs ? Object.entries(this.asset.technical_specs) : [];
  }

  get displayedUnit(): string {
    if (this.asset.unit?.name) {
      return `${this.asset.unit.name} (${this.asset.unit.code})`;
    }
    return 'Unidade Cadastrada';
  }

  get displayedEmployee(): string {
    if (this.asset.employee?.name) {
      const pos = this.asset.employee.position ? ` — ${this.asset.employee.position}` : '';
      return `${this.asset.employee.name}${pos}`;
    }
    return 'Em Estoque (Sem Atribuição)';
  }

  get isWarrantyActive(): boolean {
    if (!this.asset.warranty_expires) return false;
    const exp = new Date(this.asset.warranty_expires);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return exp >= today;
  }

  getSpecLabel(key: string): string {
    const schema = this.asset.category?.spec_schema;
    if (schema && schema[key]?.label) {
      return schema[key].label;
    }
    const map: Record<string, string> = {
      cpu: 'Processador',
      ram: 'Memória RAM',
      storage: 'Armazenamento',
      os: 'Sistema Operacional',
      tela: 'Tamanho da Tela',
      imei: 'IMEI / Serial',
      tipo: 'Tecnologia / Tipo',
      conexao: 'Conexão',
      resolucao: 'Resolução',
      cor: 'Cor / Acabamento',
      mac_address: 'Endereço MAC',
      hostname: 'Nome de Rede (Hostname)',
      last_logged_user: 'Último Usuário Conectado'
    };
    return map[key.toLowerCase()] || key.replace(/_/g, ' ').toUpperCase();
  }

  getSpecIcon(key: string): string {
    const k = key.toLowerCase();
    if (k.includes('cpu') || k.includes('proc')) return 'memory';
    if (k.includes('ram') || k.includes('mem')) return 'speed';
    if (k.includes('storage') || k.includes('armazenamento') || k.includes('ssd') || k.includes('hd')) return 'dns';
    if (k.includes('os') || k.includes('sistema')) return 'terminal';
    if (k.includes('tela') || k.includes('screen') || k.includes('display')) return 'laptop';
    if (k.includes('imei') || k.includes('serial')) return 'fingerprint';
    if (k.includes('mac') || k.includes('hostname') || k.includes('rede')) return 'lan';
    if (k.includes('usuario') || k.includes('user')) return 'person';
    if (k.includes('conex') || k.includes('porta') || k.includes('usb')) return 'cable';
    if (k.includes('tipo') || k.includes('print')) return 'print';
    if (k.includes('resol')) return 'aspect_ratio';
    return 'settings_input_component';
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'IN_STOCK': return 'status-in_stock';
      case 'IN_USE': return 'status-in_use';
      case 'MAINTENANCE': return 'status-maintenance';
      case 'DECOMMISSIONED': return 'status-decommissioned';
      default: return 'status-default';
    }
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'IN_STOCK': return 'Em Estoque';
      case 'IN_USE': return 'Em Uso';
      case 'MAINTENANCE': return 'Em Manutenção';
      case 'DECOMMISSIONED': return 'Baixado';
      default: return status;
    }
  }

  printStatement(): void {
    this.assetService.openResponsibilityStatement(this.asset.id);
  }

  goToFullDetail(): void {
    this.dialogRef.close();
    this.router.navigate(['/assets', this.asset.id]);
  }
}
