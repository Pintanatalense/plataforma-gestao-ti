import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatChipsModule } from '@angular/material/chips';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AssetCategory, AssetService } from '../../../core/services/asset.service';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';

interface SpecFieldItem {
  name: string;
  required: boolean;
}

@Component({
  selector: 'app-asset-category-list',
  standalone: true,
  imports: [
    CommonModule,
    LoadStateComponent,
    FormsModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatInputModule,
    MatFormFieldModule,
    MatTableModule,
    MatIconModule,
    MatTooltipModule,
    MatChipsModule,
    MatCheckboxModule,
    MatSnackBarModule
  ],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <div class="title-row">
            <button mat-icon-button routerLink="/assets" matTooltip="Voltar para Ativos" class="back-btn">
              <mat-icon>arrow_back</mat-icon>
            </button>
            <h1>Categorias de Ativos</h1>
          </div>
          <p>Gerencie as categorias de patrimônio e configure os campos técnicos esperados para cada tipo de equipamento.</p>
        </div>
        <div class="header-actions">
          <button mat-stroked-button routerLink="/assets" class="nav-btn">
            <mat-icon>devices</mat-icon>
            Ver Patrimônio
          </button>
        </div>
      </div>

      <div class="content-grid">
        <!-- Card de Formulário (Criar / Editar) -->
        <div class="form-card">
          <div class="card-header">
            <h3>{{ editingCategory ? 'Editar Categoria' : 'Nova Categoria' }}</h3>
            <p *ngIf="editingCategory" class="editing-subtitle">Editando: <strong>{{ editingCategory.name }}</strong></p>
          </div>

          <form [formGroup]="catForm" (ngSubmit)="onSubmit()" class="modern-form">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Nome da Categoria</mat-label>
              <input matInput formControlName="name" placeholder="Ex: Notebook, Monitor, Servidor, Switch" required>
              <mat-error *ngIf="catForm.get('name')?.hasError('required')">O nome da categoria é obrigatório</mat-error>
            </mat-form-field>
            
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Descrição (Opcional)</mat-label>
              <textarea matInput formControlName="description" rows="2" placeholder="Breve descrição dos equipamentos desta categoria..."></textarea>
            </mat-form-field>

            <!-- Seção de Campos Técnicos (Schema Dinâmico) -->
            <div class="specs-section">
              <div class="specs-header">
                <div class="specs-title">
                  <mat-icon>tune</mat-icon>
                  <span>Campos Técnicos (Especificações)</span>
                </div>
                <span class="specs-count">{{ specFields.length }} campo(s)</span>
              </div>
              <p class="specs-hint">
                Campos solicitados ao cadastrar um ativo desta categoria.
              </p>

              <!-- Presets Rápidos -->
              <div class="presets-row">
                <span class="preset-label">Modelos rápidos:</span>
                <button type="button" mat-stroked-button (click)="applyPreset('computer')" class="preset-chip">
                  Computador
                </button>
                <button type="button" mat-stroked-button (click)="applyPreset('network')" class="preset-chip">
                  Rede
                </button>
                <button type="button" mat-stroked-button (click)="applyPreset('mobile')" class="preset-chip">
                  Mobile
                </button>
              </div>

              <!-- Lista de Campos Dinâmicos -->
              <div class="spec-fields-list" *ngIf="specFields.length > 0">
                <div class="spec-field-item" *ngFor="let field of specFields; let i = index">
                  <mat-form-field appearance="outline" class="field-name-input" subscriptSizing="dynamic">
                    <mat-label>Nome do Campo</mat-label>
                    <input matInput [(ngModel)]="field.name" [ngModelOptions]="{standalone: true}" placeholder="Ex: Processador, Memória RAM">
                  </mat-form-field>

                  <mat-checkbox [(ngModel)]="field.required" [ngModelOptions]="{standalone: true}" class="field-req-check">
                    Obrigatório
                  </mat-checkbox>

                  <button type="button" mat-icon-button color="warn" (click)="removeSpecField(i)" matTooltip="Remover campo" class="remove-field-btn">
                    <mat-icon>close</mat-icon>
                  </button>
                </div>
              </div>

              <div class="spec-empty-hint" *ngIf="specFields.length === 0">
                <mat-icon>playlist_add</mat-icon>
                <span>Nenhum campo técnico adicionado. Clique abaixo para incluir.</span>
              </div>

              <button type="button" mat-stroked-button color="primary" (click)="addSpecField()" class="add-field-btn">
                <mat-icon>add</mat-icon>
                Adicionar Campo Técnico
              </button>
            </div>

            <div class="form-actions">
              <button mat-button type="button" *ngIf="editingCategory" (click)="cancelEdit()" class="cancel-btn">
                Cancelar
              </button>
              <button mat-flat-button color="primary" type="submit" [disabled]="catForm.invalid" class="submit-btn">
                <mat-icon>{{ editingCategory ? 'save' : 'add' }}</mat-icon>
                {{ editingCategory ? 'Atualizar Categoria' : 'Criar Categoria' }}
              </button>
            </div>
          </form>
        </div>

        <!-- Card de Listagem de Categorias -->
        <div class="table-card">
          <div class="table-header">
            <h3>Categorias Cadastradas</h3>
            <span class="badge-total" *ngIf="!categoriesLoading && !categoriesError">{{ categories.length }} categorias</span>
          </div>

          <app-load-state [loading]="categoriesLoading" [error]="categoriesError" [empty]="categories.length === 0"
                          emptyText="Nenhuma categoria cadastrada." loadingText="Carregando categorias…" (retry)="loadData()"></app-load-state>

          <table mat-table [dataSource]="categories" class="modern-table"
                 *ngIf="!categoriesLoading && !categoriesError && categories.length > 0">
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef> Categoria </th>
              <td mat-cell *matCellDef="let element">
                <div class="category-info">
                  <span class="category-name">{{ element.name }}</span>
                  <span class="category-desc" *ngIf="element.description">{{ element.description }}</span>
                </div>
              </td>
            </ng-container>

            <ng-container matColumnDef="specs">
              <th mat-header-cell *matHeaderCellDef> Campos Técnicos </th>
              <td mat-cell *matCellDef="let element">
                <div class="specs-preview" *ngIf="getSpecKeys(element).length > 0">
                  <span class="spec-tag" *ngFor="let key of getSpecKeys(element) | slice:0:3">
                    {{ key }}
                  </span>
                  <span class="spec-tag more" *ngIf="getSpecKeys(element).length > 3">
                    +{{ getSpecKeys(element).length - 3 }}
                  </span>
                </div>
                <span class="no-specs" *ngIf="getSpecKeys(element).length === 0">
                  Sem campos específicos
                </span>
              </td>
            </ng-container>

            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef class="actions-header"> Ações </th>
              <td mat-cell *matCellDef="let element" class="actions-cell">
                <button mat-icon-button class="action-btn edit-btn" (click)="edit(element)" matTooltip="Editar Categoria">
                  <mat-icon>edit</mat-icon>
                </button>
                <button mat-icon-button class="action-btn delete-btn" (click)="deleteCategory(element)" matTooltip="Excluir Categoria">
                  <mat-icon>delete_outline</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
            
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell empty-state" [attr.colspan]="displayedColumns.length">
                <mat-icon>category</mat-icon>
                <p>Nenhuma categoria de ativo encontrada</p>
                <span>Utilize o formulário ao lado para cadastrar a primeira categoria.</span>
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
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--mat-sys-surface, #ffffff);
      padding: 24px 32px;
      border-radius: 20px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant, #e2e8f0);

      .title-area {
        .title-row {
          display: flex;
          align-items: center;
          gap: 12px;

          .back-btn {
            color: var(--mat-sys-primary, #2563eb);
          }

          h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.5px;
            color: var(--mat-sys-primary, #1e293b);
          }
        }

        p {
          margin: 6px 0 0;
          color: var(--mat-sys-on-surface-variant, #64748b);
          font-size: 14px;
        }
      }

      .header-actions {
        display: flex;
        gap: 12px;

        .nav-btn {
          border-radius: 12px;
          font-weight: 600;
          height: 42px;
          mat-icon { margin-right: 6px; }
        }
      }

      @media (max-width: 640px) {
        flex-direction: column;
        align-items: flex-start;
        gap: 16px;
        padding: 16px 20px;

        .header-actions {
          width: 100%;
          .nav-btn {
            width: 100%;
            justify-content: center;
          }
        }
      }
    }

    .content-grid {
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 24px;
      align-items: start;
    }

    @media (max-width: 1024px) {
      .content-grid {
        grid-template-columns: 1fr;
      }
    }

    .form-card, .table-card {
      background: var(--mat-sys-surface, #ffffff);
      border-radius: 20px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant, #e2e8f0);
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
        margin-bottom: 20px;
        h3 {
          margin: 0;
          color: var(--mat-sys-primary, #1e293b);
          font-size: 19px;
          font-weight: 700;
        }
        .editing-subtitle {
          margin: 4px 0 0;
          font-size: 13px;
          color: var(--mat-sys-primary, #2563eb);
        }
      }
    }

    .modern-form {
      display: flex;
      flex-direction: column;
      gap: 12px;
      
      .full-width { width: 100%; }

      .specs-section {
        background: var(--mat-sys-surface-container-low, #f8fafc);
        border: 1px solid var(--mat-sys-outline-variant, #e2e8f0);
        border-radius: 16px;
        padding: 16px;
        margin-top: 4px;
        margin-bottom: 12px;

        .specs-header {
          display: flex;
          justify-content: space-between;
          align-items: center;

          .specs-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 700;
            color: var(--mat-sys-on-surface, #334155);

            mat-icon {
              font-size: 20px;
              width: 20px;
              height: 20px;
              color: var(--mat-sys-primary, #2563eb);
            }
          }

          .specs-count {
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            background: #e2e8f0;
            padding: 2px 8px;
            border-radius: 12px;
          }
        }

        .specs-hint {
          margin: 6px 0 12px;
          font-size: 12px;
          color: #64748b;
        }

        .presets-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 14px;

          .preset-label {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
          }

          .preset-chip {
            font-size: 11px;
            height: 28px;
            padding: 0 10px;
            border-radius: 14px;
            line-height: 28px;
          }
        }

        .spec-fields-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 12px;

          .spec-field-item {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #ffffff;
            padding: 6px 10px;
            border-radius: 10px;
            border: 1px solid #e2e8f0;

            .field-name-input {
              flex: 1;
              font-size: 13px;
            }

            .field-req-check {
              font-size: 12px;
            }

            .remove-field-btn {
              width: 32px;
              height: 32px;
              mat-icon { font-size: 18px; }
            }
          }
        }

        .spec-empty-hint {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px;
          background: #ffffff;
          border-radius: 10px;
          border: 1px dashed #cbd5e1;
          margin-bottom: 12px;
          font-size: 12px;
          color: #64748b;

          mat-icon {
            font-size: 20px;
            width: 20px;
            height: 20px;
            opacity: 0.7;
          }
        }

        .add-field-btn {
          width: 100%;
          border-radius: 10px;
          font-weight: 600;
          font-size: 13px;
          height: 38px;
          mat-icon { margin-right: 6px; }
        }
      }
      
      .form-actions {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        margin-top: 8px;
        
        .cancel-btn {
          border-radius: 12px;
          font-weight: 600;
        }
        
        .submit-btn {
          border-radius: 12px;
          padding: 0 24px;
          height: 44px;
          font-weight: 600;
          mat-icon { margin-right: 8px; }
        }
      }
    }

    .table-card {
      .table-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 24px 28px 16px;
        border-bottom: 1px solid var(--mat-sys-outline-variant, #e2e8f0);

        h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
          color: #1e293b;
        }

        .badge-total {
          font-size: 12px;
          font-weight: 600;
          background: #eff6ff;
          color: #2563eb;
          padding: 4px 12px;
          border-radius: 20px;
        }
      }
    }

    .modern-table {
      width: 100%;
      min-width: 520px;
      
      tr.mat-mdc-row {
        transition: background-color 0.2s ease;
        &:hover {
          background-color: var(--mat-sys-surface-container-highest, #f8fafc);
        }
      }

      td.mat-mdc-cell, th.mat-mdc-header-cell {
        border-bottom-color: var(--mat-sys-outline-variant, #e2e8f0);
        padding: 18px 24px;
      }
      
      th.mat-mdc-header-cell {
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-size: 11px;
        color: var(--mat-sys-on-surface-variant, #64748b);
        background: var(--mat-sys-surface-container-lowest, #f8fafc);
      }
    }

    .category-info {
      display: flex;
      flex-direction: column;
      gap: 4px;
      
      .category-name {
        font-weight: 700;
        font-size: 14.5px;
        color: #1e293b;
      }
      
      .category-desc {
        font-size: 12.5px;
        color: #64748b;
        line-height: 1.4;
      }
    }

    .specs-preview {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;

      .spec-tag {
        background: #f1f5f9;
        color: #334155;
        font-size: 11.5px;
        font-weight: 500;
        padding: 3px 10px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;

        &.more {
          background: #e2e8f0;
          font-weight: 600;
          color: #475569;
        }
      }
    }

    .no-specs {
      font-size: 12px;
      color: #94a3b8;
      font-style: italic;
    }

    .actions-header {
      text-align: right !important;
      width: 100px;
    }

    .actions-cell {
      text-align: right;
      
      .action-btn {
        transition: transform 0.2s, background-color 0.2s;
        &.edit-btn {
          color: #2563eb;
          &:hover {
            background-color: rgba(37, 99, 235, 0.1);
            transform: scale(1.1);
          }
        }
        &.delete-btn {
          color: #dc2626;
          &:hover {
            background-color: rgba(220, 38, 38, 0.1);
            transform: scale(1.1);
          }
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 56px 32px !important;
      color: #64748b;
      
      mat-icon {
        font-size: 44px;
        height: 44px;
        width: 44px;
        opacity: 0.4;
        margin-bottom: 12px;
      }
      
      p {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: #334155;
      }

      span {
        font-size: 13px;
        color: #94a3b8;
      }
    }
  `]
})
export class AssetCategoryListComponent implements OnInit {
  private assetService = inject(AssetService);
  private fb = inject(FormBuilder);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  categories: AssetCategory[] = [];
  /** Primeira carga / falha da lista (uma recarga que falha depois de carregar mantém a tabela e só avisa). */
  categoriesLoading = true;
  categoriesError: string | null = null;
  private categoriesLoaded = false;
  displayedColumns: string[] = ['name', 'specs', 'actions'];
  
  catForm: FormGroup;
  editingCategory: AssetCategory | null = null;
  specFields: SpecFieldItem[] = [];

  constructor() {
    this.catForm = this.fb.group({
      name: ['', Validators.required],
      description: ['']
    });
  }

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    if (!this.categoriesLoaded) {
      this.categoriesLoading = true;
      this.categoriesError = null;
    }
    this.assetService.getCategories().subscribe({
      next: (c) => {
        this.categories = c;
        this.categoriesLoaded = true;
        this.categoriesLoading = false;
        this.categoriesError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Não foi possível carregar as categorias de ativos.');
        if (this.categoriesLoaded) {
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        } else {
          this.categoriesLoading = false;
          this.categoriesError = msg;
        }
        this.cdr.markForCheck();
      }
    });
  }

  getSpecKeys(cat: AssetCategory): string[] {
    if (!cat.spec_schema) return [];
    return Object.keys(cat.spec_schema);
  }

  addSpecField(): void {
    this.specFields.push({ name: '', required: false });
  }

  removeSpecField(index: number): void {
    this.specFields.splice(index, 1);
  }

  applyPreset(type: 'computer' | 'network' | 'mobile'): void {
    if (type === 'computer') {
      this.specFields = [
        { name: 'Processador', required: true },
        { name: 'Memória RAM', required: true },
        { name: 'Armazenamento', required: false },
        { name: 'Sistema Operacional', required: false },
        { name: 'Hostname', required: false }
      ];
    } else if (type === 'network') {
      this.specFields = [
        { name: 'Qtd Portas', required: true },
        { name: 'Velocidade', required: false },
        { name: 'Endereço IP/MAC', required: false },
        { name: 'Gerenciável', required: false }
      ];
    } else if (type === 'mobile') {
      this.specFields = [
        { name: 'IMEI', required: true },
        { name: 'Número de Série', required: false },
        { name: 'Operadora', required: false },
        { name: 'Capacidade', required: false }
      ];
    }
  }

  edit(cat: AssetCategory): void {
    this.editingCategory = cat;
    this.catForm.patchValue({
      name: cat.name,
      description: cat.description || ''
    });

    this.specFields = [];
    if (cat.spec_schema) {
      for (const [key, val] of Object.entries(cat.spec_schema)) {
        const isReq = typeof val === 'object' && val !== null ? (val as any).required ?? false : false;
        this.specFields.push({ name: key, required: !!isReq });
      }
    }
  }

  cancelEdit(): void {
    this.editingCategory = null;
    this.catForm.reset();
    this.specFields = [];
  }

  onSubmit(): void {
    if (this.catForm.invalid) return;

    // Constrói o spec_schema JSON
    const specSchema: Record<string, any> = {};
    for (const field of this.specFields) {
      const cleanName = field.name.trim();
      if (cleanName) {
        specSchema[cleanName] = {
          type: 'string',
          required: field.required,
          label: cleanName
        };
      }
    }

    const payload: Partial<AssetCategory> = {
      name: this.catForm.value.name.trim(),
      description: this.catForm.value.description ? this.catForm.value.description.trim() : null,
      spec_schema: specSchema
    };

    if (this.editingCategory) {
      this.assetService.updateCategory(this.editingCategory.id, payload).subscribe({
        next: () => {
          this.snackBar.open('Categoria atualizada com sucesso!', 'Fechar', { duration: 3000 });
          this.loadData();
          this.cancelEdit();
        },
        error: (err) => {
          console.error('Erro ao atualizar categoria:', err);
          const msg = apiErrorMessage(err, 'Erro ao atualizar categoria.');
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        }
      });
    } else {
      this.assetService.createCategory(payload).subscribe({
        next: () => {
          this.snackBar.open('Categoria criada com sucesso!', 'Fechar', { duration: 3000 });
          this.loadData();
          this.cancelEdit();
        },
        error: (err) => {
          console.error('Erro ao criar categoria:', err);
          const msg = apiErrorMessage(err, 'Erro ao criar categoria.');
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        }
      });
    }
  }

  deleteCategory(cat: AssetCategory): void {
    if (!confirm(`Deseja realmente desativar a categoria "${cat.name}"?`)) {
      return;
    }

    this.assetService.deleteCategory(cat.id).subscribe({
      next: () => {
        this.snackBar.open(`Categoria "${cat.name}" removida.`, 'Fechar', { duration: 3000 });
        this.loadData();
        if (this.editingCategory?.id === cat.id) {
          this.cancelEdit();
        }
      },
      error: (err) => {
        console.error('Erro ao remover categoria:', err);
        const msg = apiErrorMessage(err, 'Erro ao remover categoria.');
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }
}
