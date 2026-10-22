import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { TicketService, TicketCategory, CategoryFormField } from '../ticket.service';
import { OrganizationService, Sector } from '../../../core/services/organization.service';
import { apiErrorMessage } from '../../../core/http/api-error';

interface FormFieldBuilder {
  id: string;
  label: string;
  type: 'text' | 'textarea' | 'number' | 'select' | 'checkbox' | 'date';
  required: boolean;
  placeholder: string;
  help_text: string;
  optionsText: string; // vírgula separada para edição
}

@Component({
  selector: 'app-category-list',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatTableModule,
    MatIconModule,
    MatTooltipModule,
    MatCheckboxModule,
    MatChipsModule,
    MatDividerModule,
    MatSnackBarModule
  ],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <div class="badge-header">
            <mat-icon>category</mat-icon>
            <span>Service Desk &bull; Gestão de Catálogo</span>
          </div>
          <h1>Categorias & Criador de Formulários</h1>
          <p>
            Configure as categorias de chamados, roteamento para setores e vincule formulários
            com pré-requisitos dinâmicos que o solicitante deve cumprir para abrir o chamado.
          </p>
        </div>
      </div>

      <div class="content-grid">
        <!-- FORM BUILDER & CATEGORY CARD -->
        <div class="form-card">
          <div class="card-header">
            <div class="header-icon">
              <mat-icon>{{ editingCategory ? 'edit_note' : 'add_task' }}</mat-icon>
            </div>
            <div>
              <h3>{{ editingCategory ? 'Editar Categoria & Formulário' : 'Nova Categoria & Formulário' }}</h3>
              <p class="card-subtitle">
                {{ editingCategory ? 'Altere as configurações e pré-requisitos desta categoria.' : 'Cadastre uma categoria e monte os campos do formulário.' }}
              </p>
            </div>
          </div>

          <form [formGroup]="catForm" (ngSubmit)="onSubmit()" class="modern-form">
            <!-- Dados Básicos -->
            <div class="form-section-title">
              <mat-icon>info</mat-icon> Informações Gerais
            </div>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Nome da Categoria</mat-label>
              <input matInput formControlName="name" placeholder="Ex: Substituição de Notebook" required>
              <mat-error *ngIf="catForm.get('name')?.hasError('required')">O nome é obrigatório</mat-error>
            </mat-form-field>
            
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Descrição</mat-label>
              <textarea matInput formControlName="description" rows="2" placeholder="Explicação exibida ao solicitante..."></textarea>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Setor Responsável (Roteamento Automático)</mat-label>
              <mat-select formControlName="default_sector_id">
                <mat-option [value]="null">Nenhum (Encaminhar para Triagem)</mat-option>
                <mat-option *ngFor="let s of sectors" [value]="s.id">{{ s.name }}</mat-option>
              </mat-select>
              <mat-hint>Chamados desta categoria serão direcionados automaticamente para este setor.</mat-hint>
            </mat-form-field>

            <mat-divider class="my-4"></mat-divider>

            <!-- FORM BUILDER DINÂMICO -->
            <div class="form-builder-section">
              <div class="builder-header">
                <div>
                  <div class="form-section-title">
                    <mat-icon>dynamic_form</mat-icon> Pré-requisitos & Campos Dinâmicos
                  </div>
                  <p class="builder-desc">
                    Defina os pré-requisitos obrigatórios que o solicitante deve preencher ao abrir chamados nesta categoria.
                  </p>
                </div>
                <button type="button" mat-stroked-button color="primary" (click)="addField()" class="add-field-btn">
                  <mat-icon>add</mat-icon> Adicionar Campo
                </button>
              </div>

              <!-- PRESETS RÁPIDOS -->
              <div class="presets-bar">
                <span class="presets-label"><mat-icon>bolt</mat-icon> Presets Rápidos:</span>
                <div class="presets-buttons">
                  <button type="button" class="preset-btn" (click)="applyPreset('hardware')">
                    💻 Troca de Hardware
                  </button>
                  <button type="button" class="preset-btn" (click)="applyPreset('access')">
                    🔐 Acesso a Sistema
                  </button>
                  <button type="button" class="preset-btn" (click)="applyPreset('incident')">
                    ⚠️ Incidente Crítico
                  </button>
                  <button type="button" class="preset-btn text-danger" *ngIf="fields.length > 0" (click)="clearFields()">
                    🗑️ Limpar
                  </button>
                </div>
              </div>

              <!-- LISTA DE CAMPOS DO BUILDER -->
              <div class="fields-list" *ngIf="fields.length > 0; else noFieldsTpl">
                <div *ngFor="let field of fields; let i = index" class="field-item-card" [class.is-required]="field.required">
                  <div class="field-item-header">
                    <div class="field-item-index">
                      <span class="index-badge">#{{ i + 1 }}</span>
                      <span class="field-name-preview">{{ field.label || 'Campo sem nome' }}</span>
                      <span class="required-tag" *ngIf="field.required">Pré-requisito Obrigatório</span>
                    </div>
                    <button type="button" mat-icon-button color="warn" (click)="removeField(i)" matTooltip="Remover este campo">
                      <mat-icon>delete</mat-icon>
                    </button>
                  </div>

                  <div class="field-item-body">
                    <div class="field-grid-row">
                      <mat-form-field appearance="outline" class="half-width">
                        <mat-label>Título / Rótulo do Campo</mat-label>
                        <input matInput [(ngModel)]="field.label" [ngModelOptions]="{standalone: true}" (ngModelChange)="onFieldLabelChange(field)" placeholder="Ex: Patrimônio Antigo" required>
                      </mat-form-field>

                      <mat-form-field appearance="outline" class="half-width">
                        <mat-label>Tipo de Entrada</mat-label>
                        <mat-select [(ngModel)]="field.type" [ngModelOptions]="{standalone: true}">
                          <mat-option value="text">Texto Curto</mat-option>
                          <mat-option value="textarea">Texto Longo / Justificativa</mat-option>
                          <mat-option value="number">Número</mat-option>
                          <mat-option value="select">Seleção (Dropdown)</mat-option>
                          <mat-option value="checkbox">Confirmação / Termo (Sim/Não)</mat-option>
                          <mat-option value="date">Data</mat-option>
                        </mat-select>
                      </mat-form-field>
                    </div>

                    <!-- Opções para dropdown -->
                    <div *ngIf="field.type === 'select'" class="select-options-wrap">
                      <mat-form-field appearance="outline" class="full-width">
                        <mat-label>Opções de Escolha (separadas por vírgula)</mat-label>
                        <input matInput [(ngModel)]="field.optionsText" [ngModelOptions]="{standalone: true}" placeholder="Ex: Defeito, Upgrade, Danificado">
                        <mat-hint>O usuário poderá selecionar apenas uma dessas opções.</mat-hint>
                      </mat-form-field>
                    </div>

                    <div class="field-grid-row">
                      <mat-form-field appearance="outline" class="half-width">
                        <mat-label>Texto de Ajuda / Placeholder</mat-label>
                        <input matInput [(ngModel)]="field.placeholder" [ngModelOptions]="{standalone: true}" placeholder="Ex: Digite o número PAT-...">
                      </mat-form-field>

                      <div class="required-checkbox-wrap">
                        <mat-checkbox [(ngModel)]="field.required" [ngModelOptions]="{standalone: true}" color="primary">
                          <strong>Pré-requisito Obrigatório</strong>
                          <span class="checkbox-hint">(Bloqueia o chamado se não preenchido)</span>
                        </mat-checkbox>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <ng-template #noFieldsTpl>
                <div class="no-fields-state">
                  <mat-icon>playlist_add</mat-icon>
                  <p>Nenhum pré-requisito adicional configurado para esta categoria.</p>
                  <span>Clique em "Adicionar Campo" ou escolha um dos Presets Rápidos acima para criar pré-requisitos.</span>
                </div>
              </ng-template>

              <!-- LIVE PREVIEW ACCORDION -->
              <div class="live-preview-box" *ngIf="fields.length > 0">
                <div class="preview-header">
                  <mat-icon>visibility</mat-icon>
                  <span>Prévia em Tempo Real (Visão do Solicitante)</span>
                </div>
                <div class="preview-content">
                  <div *ngFor="let f of fields" class="preview-item">
                    <span class="preview-label">
                      {{ f.label || 'Campo' }}
                      <span class="req-star" *ngIf="f.required">*</span>
                    </span>
                    <span class="preview-type-pill">{{ f.type }}</span>
                    <span class="preview-hint" *ngIf="f.placeholder">{{ f.placeholder }}</span>
                  </div>
                </div>
              </div>

            </div>

            <!-- BOTÕES DE AÇÃO -->
            <div class="form-actions">
              <button mat-button type="button" *ngIf="editingCategory" (click)="cancelEdit()" class="cancel-btn">
                Cancelar
              </button>
              <button mat-flat-button color="primary" type="submit" [disabled]="catForm.invalid" class="submit-btn">
                <mat-icon>{{ editingCategory ? 'save' : 'add_circle' }}</mat-icon>
                {{ editingCategory ? 'Atualizar Categoria' : 'Salvar Categoria' }}
              </button>
            </div>
          </form>
        </div>

        <!-- LISTA / TABELA DE CATEGORIAS -->
        <div class="table-card">
          <div class="table-header-box">
            <h3>Categorias Cadastradas</h3>
            <span class="counter-badge">{{ categories.length }} categorias</span>
          </div>

          <table mat-table [dataSource]="categories" class="modern-table">
            <!-- Categoria -->
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef> Categoria </th>
              <td mat-cell *matCellDef="let element">
                <div class="category-info">
                  <span class="category-name">{{ element.name }}</span>
                  <span class="category-desc" *ngIf="element.description">{{ element.description }}</span>
                </div>
              </td>
            </ng-container>

            <!-- Roteamento -->
            <ng-container matColumnDef="sector">
              <th mat-header-cell *matHeaderCellDef> Roteamento (Fila) </th>
              <td mat-cell *matCellDef="let element"> 
                <span class="status-badge" [class.routed]="element.default_sector_id" [class.triage]="!element.default_sector_id">
                  <mat-icon class="badge-icon">{{ element.default_sector_id ? 'alt_route' : 'filter_alt' }}</mat-icon>
                  {{ element.default_sector_id ? getSectorName(element.default_sector_id) : 'Triagem' }}
                </span>
              </td>
            </ng-container>

            <!-- Pré-requisitos vinculados -->
            <ng-container matColumnDef="prerequisites">
              <th mat-header-cell *matHeaderCellDef> Pré-requisitos </th>
              <td mat-cell *matCellDef="let element">
                <div *ngIf="element.form_schema && element.form_schema.length > 0; else noReqs">
                  <span class="prereq-badge">
                    <mat-icon>checklist</mat-icon>
                    {{ element.form_schema.length }} campo(s)
                  </span>
                  <span class="prereq-req-count" *ngIf="getRequiredCount(element) > 0">
                    ({{ getRequiredCount(element) }} obrigatórios)
                  </span>
                  <div class="prereq-tags">
                    <span *ngFor="let f of element.form_schema.slice(0, 3)" class="field-mini-tag">
                      {{ f.label }}<span *ngIf="f.required" class="text-danger">*</span>
                    </span>
                    <span *ngIf="element.form_schema.length > 3" class="field-mini-more">
                      +{{ element.form_schema.length - 3 }}
                    </span>
                  </div>
                </div>
                <ng-template #noReqs>
                  <span class="no-prereq-badge">
                    <mat-icon>remove</mat-icon> Sem requisitos
                  </span>
                </ng-template>
              </td>
            </ng-container>

            <!-- Ações -->
            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef class="actions-header"> Ações </th>
              <td mat-cell *matCellDef="let element" class="actions-cell">
                <button mat-icon-button class="action-btn edit-btn" (click)="edit(element)" matTooltip="Editar categoria e formulário">
                  <mat-icon>edit</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
            
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell empty-state" [attr.colspan]="displayedColumns.length">
                <mat-icon>category</mat-icon>
                <p>Nenhuma categoria encontrada</p>
              </td>
            </tr>
          </table>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .page-container {
      display: flex;
      flex-direction: column;
      gap: 24px;
      width: 100%;
      box-sizing: border-box;
      animation: fadeIn 0.4s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .page-header {
      background: #ffffff;
      padding: 24px 32px;
      border-radius: 24px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid #e2e8f0;

      @media (max-width: 640px) {
        padding: 18px 20px;
      }

      .badge-header {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #2563eb;
        background: #eff6ff;
        padding: 4px 12px;
        border-radius: 20px;
        margin-bottom: 12px;

        mat-icon {
          font-size: 16px;
          height: 16px;
          width: 16px;
        }
      }

      h1 {
        margin: 0;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #0f172a;
      }

      p {
        margin: 8px 0 0;
        color: #64748b;
        font-size: 15px;
        max-width: 800px;
        line-height: 1.5;
      }
    }

    .content-grid {
      display: grid;
      grid-template-columns: 460px 1fr;
      gap: 24px;
      align-items: start;

      @media (max-width: 1100px) {
        grid-template-columns: 1fr;
      }
    }

    .form-card, .table-card {
      background: #ffffff;
      border-radius: 24px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid #e2e8f0;
    }

    .table-card {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    .form-card {
      padding: 28px;

      @media (max-width: 640px) {
        padding: 20px 16px;
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-bottom: 24px;

        .header-icon {
          width: 48px;
          height: 48px;
          border-radius: 14px;
          background: #eff6ff;
          color: #2563eb;
          display: flex;
          align-items: center;
          justify-content: center;

          mat-icon {
            font-size: 26px;
            width: 26px;
            height: 26px;
          }
        }

        h3 {
          margin: 0;
          color: #0f172a;
          font-size: 19px;
          font-weight: 700;
        }

        .card-subtitle {
          margin: 4px 0 0;
          font-size: 13px;
          color: #64748b;
        }
      }
    }

    .form-section-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 700;
      color: #1e293b;
      margin-bottom: 12px;

      mat-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
        color: #2563eb;
      }
    }

    .modern-form {
      display: flex;
      flex-direction: column;
      gap: 8px;

      .full-width { width: 100%; }
      .half-width { flex: 1; }
    }

    .form-builder-section {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 18px;
      padding: 20px;
      margin-top: 8px;

      .builder-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 16px;

        .builder-desc {
          margin: 4px 0 0;
          font-size: 12.5px;
          color: #64748b;
          line-height: 1.4;
        }

        .add-field-btn {
          border-radius: 10px;
          font-weight: 600;
          white-space: nowrap;
          mat-icon { margin-right: 4px; }
        }
      }
    }

    .presets-bar {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      padding: 10px 14px;
      background: #ffffff;
      border: 1px dashed #cbd5e1;
      border-radius: 12px;
      margin-bottom: 16px;

      .presets-label {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        font-weight: 700;
        color: #475569;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          color: #f59e0b;
        }
      }

      .presets-buttons {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;

        .preset-btn {
          background: #f1f5f9;
          border: 1px solid #e2e8f0;
          border-radius: 8px;
          padding: 4px 10px;
          font-size: 12px;
          font-weight: 600;
          color: #334155;
          cursor: pointer;
          transition: all 0.15s;

          &:hover {
            background: #e2e8f0;
            color: #0f172a;
          }

          &.text-danger {
            color: #ef4444;
            &:hover { background: #fee2e2; }
          }
        }
      }
    }

    .fields-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 16px;
    }

    .field-item-card {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 14px 16px;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.02);
      transition: border-color 0.2s;

      &.is-required {
        border-left: 4px solid #ef4444;
      }

      .field-item-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;

        .field-item-index {
          display: flex;
          align-items: center;
          gap: 8px;

          .index-badge {
            background: #e2e8f0;
            color: #475569;
            font-size: 11px;
            font-weight: 800;
            padding: 2px 6px;
            border-radius: 6px;
          }

          .field-name-preview {
            font-weight: 700;
            font-size: 14px;
            color: #1e293b;
          }

          .required-tag {
            background: #fee2e2;
            color: #b91c1c;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
          }
        }
      }

      .field-item-body {
        display: flex;
        flex-direction: column;
        gap: 6px;

        .field-grid-row {
          display: flex;
          gap: 12px;
          align-items: center;

          @media (max-width: 600px) {
            flex-direction: column;
          }
        }

        .required-checkbox-wrap {
          flex: 1;
          display: flex;
          align-items: center;
          padding: 8px 12px;
          background: #f8fafc;
          border-radius: 8px;
          border: 1px solid #e2e8f0;

          .checkbox-hint {
            display: block;
            font-size: 11px;
            color: #64748b;
          }
        }
      }
    }

    .no-fields-state {
      text-align: center;
      padding: 28px 16px;
      color: #64748b;

      mat-icon {
        font-size: 36px;
        width: 36px;
        height: 36px;
        opacity: 0.6;
        margin-bottom: 8px;
      }

      p {
        margin: 0;
        font-weight: 600;
        font-size: 14px;
        color: #334155;
      }

      span {
        display: block;
        font-size: 12px;
        margin-top: 4px;
      }
    }

    .live-preview-box {
      margin-top: 14px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-radius: 12px;
      padding: 12px 16px;

      .preview-header {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 10px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          color: #2563eb;
        }
      }

      .preview-content {
        display: flex;
        flex-direction: column;
        gap: 8px;

        .preview-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 6px 10px;
          background: #f8fafc;
          border-radius: 8px;
          font-size: 12.5px;

          .preview-label {
            font-weight: 600;
            color: #1e293b;
            .req-star { color: #ef4444; font-weight: 800; margin-left: 2px; }
          }

          .preview-type-pill {
            background: #e2e8f0;
            color: #475569;
            font-size: 10.5px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            text-transform: uppercase;
          }

          .preview-hint {
            color: #94a3b8;
            font-size: 11.5px;
            font-style: italic;
          }
        }
      }
    }

    .form-actions {
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-top: 20px;

      .cancel-btn {
        border-radius: 12px;
        font-weight: 600;
      }

      .submit-btn {
        border-radius: 12px;
        padding: 0 24px;
        height: 44px;
        font-weight: 600;
        mat-icon { margin-right: 6px; }
      }
    }

    .table-card {
      .table-header-box {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 24px 28px 16px;
        border-bottom: 1px solid #e2e8f0;

        h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
          color: #0f172a;
        }

        .counter-badge {
          background: #eff6ff;
          color: #2563eb;
          font-size: 12px;
          font-weight: 700;
          padding: 4px 12px;
          border-radius: 20px;
        }
      }
    }

    .modern-table {
      width: 100%;
      min-width: 580px;

      tr.mat-mdc-row:hover {
        background-color: #f8fafc;
      }

      td.mat-mdc-cell, th.mat-mdc-header-cell {
        border-bottom-color: #e2e8f0;
        padding: 16px 24px;
      }

      th.mat-mdc-header-cell {
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        font-size: 11.5px;
        color: #64748b;
        background: #f8fafc;
      }
    }

    .category-info {
      display: flex;
      flex-direction: column;
      gap: 3px;

      .category-name {
        font-weight: 700;
        font-size: 14.5px;
        color: #0f172a;
      }

      .category-desc {
        font-size: 12.5px;
        color: #64748b;
      }
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 11.5px;
      font-weight: 700;

      .badge-icon {
        font-size: 15px;
        height: 15px;
        width: 15px;
      }

      &.routed {
        background-color: #eff6ff;
        color: #2563eb;
      }

      &.triage {
        background-color: #f1f5f9;
        color: #64748b;
      }
    }

    .prereq-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: #f0fdf4;
      color: #16a34a;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 700;

      mat-icon {
        font-size: 15px;
        height: 15px;
        width: 15px;
      }
    }

    .prereq-req-count {
      margin-left: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: #dc2626;
    }

    .prereq-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 6px;

      .field-mini-tag {
        background: #f1f5f9;
        color: #334155;
        font-size: 11px;
        padding: 1px 6px;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
      }

      .field-mini-more {
        font-size: 10.5px;
        color: #64748b;
        font-weight: 600;
      }
    }

    .no-prereq-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: #94a3b8;
      font-size: 12px;
      font-style: italic;

      mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }
    }

    .actions-header {
      text-align: right !important;
      width: 80px;
    }

    .actions-cell {
      text-align: right;

      .action-btn.edit-btn {
        color: #2563eb;
        &:hover {
          background-color: #eff6ff;
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 48px 32px !important;
      color: #64748b;

      mat-icon {
        font-size: 40px;
        height: 40px;
        width: 40px;
        opacity: 0.5;
        margin-bottom: 12px;
      }

      p {
        margin: 0;
        font-size: 15px;
        font-weight: 600;
      }
    }

    .my-4 { margin: 16px 0; }
    .text-danger { color: #ef4444; }
  `]
})
export class CategoryListComponent implements OnInit {
  private ticketService = inject(TicketService);
  private orgService = inject(OrganizationService);
  private fb = inject(FormBuilder);
  private snackBar = inject(MatSnackBar);

  categories: TicketCategory[] = [];
  sectors: Sector[] = [];
  displayedColumns: string[] = ['name', 'sector', 'prerequisites', 'actions'];
  
  catForm: FormGroup;
  editingCategory: TicketCategory | null = null;
  fields: FormFieldBuilder[] = [];

  constructor() {
    this.catForm = this.fb.group({
      name: ['', Validators.required],
      description: [''],
      default_sector_id: [null]
    });
  }

  ngOnInit() {
    this.loadData();
    this.orgService.getSectors().subscribe({
      next: (s) => (this.sectors = s),
      error: () => {}
    });
  }

  loadData() {
    this.ticketService.getCategories().subscribe({
      next: (c) => (this.categories = c),
      error: (err) => {
        this.snackBar.open('Erro ao carregar categorias', 'Fechar', { duration: 3000 });
      }
    });
  }

  getSectorName(id: string): string {
    const s = this.sectors.find(x => x.id === id);
    return s ? s.name : 'Desconhecido';
  }

  getRequiredCount(element: TicketCategory): number {
    if (!element.form_schema) return 0;
    return element.form_schema.filter(f => f.required).length;
  }

  // FIELD BUILDER LOGIC
  addField() {
    const count = this.fields.length + 1;
    this.fields.push({
      id: `campo_${count}_${Date.now().toString().slice(-4)}`,
      label: `Novo Campo ${count}`,
      type: 'text',
      required: true,
      placeholder: '',
      help_text: '',
      optionsText: ''
    });
  }

  removeField(index: number) {
    this.fields.splice(index, 1);
  }

  clearFields() {
    this.fields = [];
  }

  onFieldLabelChange(field: FormFieldBuilder) {
    // Gera ID único normalizado se ainda for campo padrão
    if (!field.id || field.id.startsWith('campo_')) {
      const slug = field.label
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]/g, '_')
        .replace(/_+/g, '_')
        .slice(0, 30);
      if (slug) {
        field.id = slug;
      }
    }
  }

  applyPreset(preset: 'hardware' | 'access' | 'incident') {
    if (preset === 'hardware') {
      this.fields = [
        {
          id: 'patrimonio_anterior',
          label: 'Patrimônio Anterior',
          type: 'text',
          required: true,
          placeholder: 'Ex: PAT-00123',
          help_text: 'Número de patrimônio gravado na etiqueta do equipamento.',
          optionsText: ''
        },
        {
          id: 'motivo_troca',
          label: 'Motivo da Troca',
          type: 'select',
          required: true,
          placeholder: 'Selecione o motivo principal',
          help_text: 'Justificativa técnica para substituição do bem.',
          optionsText: 'Defeito Físico, Lentidão Crítica, Upgrade de Cargo, Dano Acidental'
        },
        {
          id: 'termo_devolucao',
          label: 'Ciente da devolução imediata do equipamento defeituoso',
          type: 'checkbox',
          required: true,
          placeholder: '',
          help_text: 'O equipamento antigo deve ser devolvido na bancada da TI.',
          optionsText: ''
        },
        {
          id: 'detalhes_defeito',
          label: 'Sintomas e Mensagens de Erro',
          type: 'textarea',
          required: false,
          placeholder: 'Descreva os erros que ocorrem, frequência, se liga, etc.',
          help_text: '',
          optionsText: ''
        }
      ];
      this.snackBar.open('Preset "Troca de Hardware" carregado!', 'OK', { duration: 2500 });
    } else if (preset === 'access') {
      this.fields = [
        {
          id: 'sistema_solicitado',
          label: 'Sistema / Aplicação Desejada',
          type: 'select',
          required: true,
          placeholder: 'Selecione o sistema',
          help_text: 'Aplicação interna ou nuvem.',
          optionsText: 'ERP Corporativo, CRM Vendas, VPN Acesso Remoto, Banco de Dados Staging, Gestão TI'
        },
        {
          id: 'nivel_permissao',
          label: 'Nível de Permissão',
          type: 'select',
          required: true,
          placeholder: 'Tipo de acesso',
          help_text: '',
          optionsText: 'Apenas Leitura, Operador Padrão, Gestor / Supervisor'
        },
        {
          id: 'aprovador_gestor',
          label: 'Gestor Responsável pela Aprovação',
          type: 'text',
          required: true,
          placeholder: 'Nome do gestor da área',
          help_text: 'Necessário para compliance e auditoria.',
          optionsText: ''
        },
        {
          id: 'justificativa_negocio',
          label: 'Justificativa de Negócio',
          type: 'textarea',
          required: true,
          placeholder: 'Por que este acesso é indispensável para suas funções?',
          help_text: '',
          optionsText: ''
        }
      ];
      this.snackBar.open('Preset "Acesso a Sistema" carregado!', 'OK', { duration: 2500 });
    } else if (preset === 'incident') {
      this.fields = [
        {
          id: 'sistema_afetado',
          label: 'Serviço ou Sistema Afetado',
          type: 'text',
          required: true,
          placeholder: 'Ex: Internet, E-mail, Impressora',
          help_text: '',
          optionsText: ''
        },
        {
          id: 'impacto_operacional',
          label: 'Impacto Operacional',
          type: 'select',
          required: true,
          placeholder: 'Grau de paralisação',
          help_text: '',
          optionsText: 'Individual (Apenas meu posto), Setorial (Todo meu setor), Geral (Toda a empresa)'
        },
        {
          id: 'horario_inicio',
          label: 'Horário de Início da Falha',
          type: 'text',
          required: true,
          placeholder: 'Ex: 14h30 de hoje',
          help_text: '',
          optionsText: ''
        }
      ];
      this.snackBar.open('Preset "Incidente Crítico" carregado!', 'OK', { duration: 2500 });
    }
  }

  edit(cat: TicketCategory) {
    this.editingCategory = cat;
    this.catForm.patchValue({
      name: cat.name,
      description: cat.description,
      default_sector_id: cat.default_sector_id
    });

    if (cat.form_schema && Array.isArray(cat.form_schema)) {
      this.fields = cat.form_schema.map(f => ({
        id: f.id,
        label: f.label,
        type: f.type,
        required: f.required,
        placeholder: f.placeholder || '',
        help_text: f.help_text || '',
        optionsText: f.options ? f.options.join(', ') : ''
      }));
    } else {
      this.fields = [];
    }
  }

  cancelEdit() {
    this.editingCategory = null;
    this.catForm.reset();
    this.fields = [];
  }

  onSubmit() {
    if (this.catForm.valid) {
      // Constrói o form_schema a partir dos builders
      const schema: CategoryFormField[] = this.fields.map((f, idx) => {
        const id = f.id.trim() || `campo_${idx + 1}`;
        const options = f.type === 'select' && f.optionsText
          ? f.optionsText.split(',').map(o => o.trim()).filter(Boolean)
          : undefined;

        return {
          id: id,
          label: f.label.trim(),
          type: f.type,
          required: !!f.required,
          placeholder: f.placeholder?.trim() || undefined,
          help_text: f.help_text?.trim() || undefined,
          options: options
        };
      });

      const payload = {
        ...this.catForm.value,
        form_schema: schema
      };

      if (this.editingCategory) {
        this.ticketService.updateCategory(this.editingCategory.id, payload).subscribe({
          next: () => {
            this.snackBar.open('Categoria e formulário atualizados!', 'OK', { duration: 3000 });
            this.loadData();
            this.cancelEdit();
          },
          error: (err) => {
            const msg = apiErrorMessage(err, 'Erro ao atualizar categoria');
            this.snackBar.open(msg, 'Fechar', { duration: 5000 });
          }
        });
      } else {
        this.ticketService.createCategory(payload).subscribe({
          next: () => {
            this.snackBar.open('Categoria e formulário criados com sucesso!', 'OK', { duration: 3000 });
            this.loadData();
            this.cancelEdit();
          },
          error: (err) => {
            const msg = apiErrorMessage(err, 'Erro ao criar categoria');
            this.snackBar.open(msg, 'Fechar', { duration: 5000 });
          }
        });
      }
    }
  }
}
