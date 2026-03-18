import React, { useMemo, useEffect } from 'react';
import { TooltipAnchor } from '@librechat/client';
import { getConfigDefaults } from 'librechat-data-provider';
import type { ModelSelectorProps } from '~/common';
import {
  renderModelSpecs,
  renderEndpoints,
  renderSearchResults,
  renderCustomGroups,
} from './components';
import { ModelSelectorProvider, useModelSelectorContext } from './ModelSelectorContext';
import { ModelSelectorChatProvider } from './ModelSelectorChatContext';
import { getSelectedIcon, getDisplayValue } from './utils';
import { CustomMenu as Menu } from './CustomMenu';
import DialogManager from './DialogManager';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';

function ModelSelectorContent() {
  const localize = useLocalize();

  const { user } = useAuthContext();
  const isRegularUser = user?.role === 'USER';

  const {
    // LibreChat
    agentsMap,
    modelSpecs,
    mappedEndpoints,
    endpointsConfig,
    // State
    searchValue,
    searchResults,
    selectedValues,
    // Functions
    setSearchValue,
    setSelectedValues,
    // Dialog
    keyDialogOpen,
    onOpenChange,
    keyDialogEndpoint,
  } = useModelSelectorContext();

  const defaultAgentId = useMemo(() => {
    if (!agentsMap) return '';
    const ids = Object.keys(agentsMap);
    return ids.length > 0 ? ids[0] : '';
  }, [agentsMap]);

  useEffect(() => {
  
    if (isRegularUser && defaultAgentId !== '') {
      
      localStorage.setItem('lastSelectedEndpoint', '"agents"');

      if (selectedValues.endpoint !== 'agents' || selectedValues.model !== defaultAgentId) {
        setSelectedValues({
          endpoint: 'agents',
          model: defaultAgentId,
          modelSpec: '',
        });
      }
    }
  }, [isRegularUser, defaultAgentId, selectedValues.endpoint, selectedValues.model, setSelectedValues]);

  const filteredEndpoints = useMemo(() => {
    if (!mappedEndpoints) return [];
    if (isRegularUser) {
      return mappedEndpoints.filter((ep: any) => {
        const epName = typeof ep === 'string' ? ep : (ep?.endpoint || ep?.name || ep?.value || '');
        return epName.toLowerCase().includes('agent');
      });
    }
    return mappedEndpoints;
  }, [mappedEndpoints, isRegularUser]);

  const filteredSearchResults = useMemo(() => {
    if (!searchResults) return undefined;
    if (isRegularUser) {
      return searchResults.filter((item: any) => {
        const itemName = typeof item === 'string' ? item : (item?.endpoint || item?.value || '');
        return itemName.toLowerCase().includes('agent');
      });
    }
    return searchResults;
  }, [searchResults, isRegularUser]);

  const selectedIcon = useMemo(
    () =>
      getSelectedIcon({
        mappedEndpoints: mappedEndpoints ?? [],
        selectedValues,
        modelSpecs,
        endpointsConfig,
      }),
    [mappedEndpoints, selectedValues, modelSpecs, endpointsConfig],
  );
  
  const selectedDisplayValue = useMemo(
    () =>
      getDisplayValue({
        localize,
        agentsMap,
        modelSpecs,
        selectedValues,
        mappedEndpoints,
      }),
    [localize, agentsMap, modelSpecs, selectedValues, mappedEndpoints],
  );

  const trigger = (
    <TooltipAnchor
      aria-label={localize('com_ui_select_model')}
      description={localize('com_ui_select_model')}
      render={
        <button
          className="my-1 flex h-10 w-full max-w-[70vw] items-center justify-center gap-2 rounded-xl border border-border-light bg-presentation px-3 py-2 text-sm text-text-primary hover:bg-surface-active-alt"
          aria-label={localize('com_ui_select_model')}
        >
          {selectedIcon && React.isValidElement(selectedIcon) && (
            <div className="flex flex-shrink-0 items-center justify-center overflow-hidden">
              {selectedIcon}
            </div>
          )}
          <span className="flex-grow truncate text-left">{selectedDisplayValue}</span>
        </button>
      }
    />
  );

  return (
    <div className="relative flex w-full max-w-md flex-col items-center gap-2">
      <Menu
        values={selectedValues}
        onValuesChange={(values: Record<string, any>) => {
          setSelectedValues({
            endpoint: values.endpoint || '',
            model: values.model || '',
            modelSpec: values.modelSpec || '',
          });
        }}
        onSearch={(value) => setSearchValue(value)}
        combobox={<input id="model-search" placeholder=" " />}
        comboboxLabel={localize('com_endpoint_search_models')}
        trigger={trigger}
      >
        {filteredSearchResults ? (
          renderSearchResults(filteredSearchResults, localize, searchValue)
        ) : (
          <>
            {!isRegularUser && renderModelSpecs(
              modelSpecs?.filter((spec) => !spec.group) || [],
              selectedValues.modelSpec || '',
            )}
            
            {renderEndpoints(filteredEndpoints)}
            
            {!isRegularUser && renderCustomGroups(modelSpecs || [], mappedEndpoints ?? [])}
          </>
        )}
      </Menu>
      <DialogManager
        keyDialogOpen={keyDialogOpen}
        onOpenChange={onOpenChange}
        endpointsConfig={endpointsConfig || {}}
        keyDialogEndpoint={keyDialogEndpoint || undefined}
      />
    </div>
  );
}

export default function ModelSelector({ startupConfig }: ModelSelectorProps) {
  const interfaceConfig = startupConfig?.interface ?? getConfigDefaults().interface;
  const modelSpecs = startupConfig?.modelSpecs?.list ?? [];

  if (interfaceConfig.modelSelect === false && modelSpecs.length === 0) {
    return null;
  }

  return (
    <ModelSelectorChatProvider>
      <ModelSelectorProvider startupConfig={startupConfig}>
        <ModelSelectorContent />
      </ModelSelectorProvider>
    </ModelSelectorChatProvider>
  );
}