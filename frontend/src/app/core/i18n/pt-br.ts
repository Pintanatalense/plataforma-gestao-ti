import { registerLocaleData } from '@angular/common';
import localePt from '@angular/common/locales/pt';

/**
 * Nomes de dia e mês em português para o `DatePipe` (`{{ d | date: 'EEE dd/MM' : undefined : PT_BR }}`).
 * O app continua no idioma padrão para números; só as datas com nome de dia ou mês passam este locale.
 * Registrar aqui (e não no main.ts) vale também nos testes, que importam o componente.
 */
registerLocaleData(localePt, 'pt-BR');

export const PT_BR = 'pt-BR';
